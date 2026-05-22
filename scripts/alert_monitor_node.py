#!/usr/bin/env python3
"""Monitor robot sensor topics and publish alerts when thresholds are exceeded.

Detects:
  COLLISION        — LaserScan min range below threshold
  VELOCITY_EXCEEDED — Odometry linear/angular velocity above threshold
  CONNECTION_LOSS  — No message received on any topic for a robot within timeout
  LOW_BATTERY      — BatteryState percentage or voltage below threshold

Publishes:
  /robot_alerts         (std_msgs/String) — one JSON alert per message
  /robot_alerts_history (std_msgs/String) — full ring buffer (50 alerts) every 5s

Exposes Prometheus metrics on :8888 for Grafana scraping.
"""

import json
import math
import os
import time
import uuid
from collections import deque

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from prometheus_client import Counter, Gauge, start_http_server
from sensor_msgs.msg import BatteryState, LaserScan
from std_msgs.msg import String

# ── Prometheus metrics (module-level, shared across all node instances) ──
_alert_counter = Counter(
    'robot_alert_total', 'Total alerts fired', ['robot_id', 'alert_type']
)
_scan_gauge = Gauge('robot_min_scan_range', 'Minimum laser scan range (m)', ['robot_id'])
_vel_lin_gauge = Gauge('robot_velocity_linear', 'Linear velocity X (m/s)', ['robot_id'])
_bat_pct_gauge = Gauge('robot_battery_percentage', 'Battery percentage (0-100)', ['robot_id'])


class AlertMonitorNode(Node):
    def __init__(self, num_robots: int):
        super().__init__('alert_monitor')
        self.num_robots = num_robots

        # Thresholds (env-overridable)
        self.scan_min_m = float(os.environ.get('ALERT_SCAN_MIN_M', '0.20'))
        self.vel_linear_max = float(os.environ.get('ALERT_VEL_LINEAR_MAX', '0.50'))
        self.vel_angular_max = float(os.environ.get('ALERT_VEL_ANGULAR_MAX', '2.00'))
        self.conn_timeout_s = float(os.environ.get('ALERT_CONN_TIMEOUT_S', '5.0'))
        self.bat_pct_min = float(os.environ.get('ALERT_BATTERY_PCT_MIN', '20.0'))
        self.bat_volt_min = float(os.environ.get('ALERT_BATTERY_VOLT_MIN', '10.5'))

        # State
        self.alert_buffer: deque = deque(maxlen=50)
        self.last_alert_time: dict = {}   # (robot_idx, alert_type) -> timestamp
        self.last_msg_time: dict = {}     # robot_idx -> timestamp

        # Publishers
        self.alert_pub = self.create_publisher(String, '/robot_alerts', 10)
        self.history_pub = self.create_publisher(String, '/robot_alerts_history', 1)

        # Subscribe to per-robot topics
        for i in range(num_robots):
            ns = f'tb3_{i}'
            self.last_msg_time[i] = time.time()
            self.create_subscription(
                LaserScan, f'/{ns}/scan',
                lambda m, n=ns, idx=i: self._on_scan(m, n, idx), 10
            )
            self.create_subscription(
                Odometry, f'/{ns}/odom',
                lambda m, n=ns, idx=i: self._on_odom(m, n, idx), 10
            )
            self.create_subscription(
                BatteryState, f'/{ns}/battery_state',
                lambda m, n=ns, idx=i: self._on_battery(m, n, idx), 10
            )

        # Timers
        self.create_timer(1.0, self._check_connection_timeouts)
        self.create_timer(5.0, self._publish_history)

        self.get_logger().info(
            f'Alert monitor started for {num_robots} robot(s) — Prometheus on :8888'
        )

    # ── Subscription callbacks ──────────────────────────────────────────────

    def _on_scan(self, msg: LaserScan, ns: str, idx: int) -> None:
        self.last_msg_time[idx] = time.time()
        valid = [
            r for r in msg.ranges
            if msg.range_min <= r <= msg.range_max
            and not math.isnan(r)
            and not math.isinf(r)
        ]
        min_range = min(valid) if valid else float('inf')
        _scan_gauge.labels(robot_id=str(idx)).set(min_range)
        if min_range < self.scan_min_m:
            self._fire_alert(
                idx, 'COLLISION', 'critical',
                f'{ns}: obstacle at {min_range:.2f} m',
                min_range, self.scan_min_m
            )

    def _on_odom(self, msg: Odometry, ns: str, idx: int) -> None:
        self.last_msg_time[idx] = time.time()
        lin_x = msg.twist.twist.linear.x
        ang_z = msg.twist.twist.angular.z
        _vel_lin_gauge.labels(robot_id=str(idx)).set(abs(lin_x))
        if abs(lin_x) > self.vel_linear_max:
            self._fire_alert(
                idx, 'VELOCITY_EXCEEDED', 'warning',
                f'{ns}: linear vel {lin_x:.2f} m/s',
                abs(lin_x), self.vel_linear_max
            )
        if abs(ang_z) > self.vel_angular_max:
            self._fire_alert(
                idx, 'VELOCITY_EXCEEDED', 'warning',
                f'{ns}: angular vel {ang_z:.2f} rad/s',
                abs(ang_z), self.vel_angular_max
            )

    def _on_battery(self, msg: BatteryState, ns: str, idx: int) -> None:
        self.last_msg_time[idx] = time.time()
        # sensor_msgs/BatteryState.percentage is 0.0–1.0
        pct = msg.percentage * 100.0
        volt = msg.voltage
        _bat_pct_gauge.labels(robot_id=str(idx)).set(pct)
        if pct < self.bat_pct_min:
            self._fire_alert(
                idx, 'LOW_BATTERY', 'warning',
                f'{ns}: battery at {pct:.0f}%',
                pct, self.bat_pct_min
            )
        if volt < self.bat_volt_min:
            self._fire_alert(
                idx, 'LOW_BATTERY', 'warning',
                f'{ns}: voltage at {volt:.1f} V',
                volt, self.bat_volt_min
            )

    # ── Timer callbacks ─────────────────────────────────────────────────────

    def _check_connection_timeouts(self) -> None:
        now = time.time()
        for idx in range(self.num_robots):
            elapsed = now - self.last_msg_time.get(idx, now)
            if elapsed > self.conn_timeout_s:
                self._fire_alert(
                    idx, 'CONNECTION_LOSS', 'critical',
                    f'tb3_{idx}: no data for {elapsed:.0f}s',
                    elapsed, self.conn_timeout_s
                )

    def _publish_history(self) -> None:
        msg = String()
        msg.data = json.dumps(list(self.alert_buffer))
        self.history_pub.publish(msg)

    # ── Alert dispatch ──────────────────────────────────────────────────────

    def _fire_alert(
        self,
        robot_idx: int,
        alert_type: str,
        severity: str,
        message: str,
        value: float,
        threshold: float,
    ) -> None:
        key = (robot_idx, alert_type)
        now = time.time()
        if now - self.last_alert_time.get(key, 0.0) < 1.0:
            return
        self.last_alert_time[key] = now

        alert = {
            'id': str(uuid.uuid4()),
            'timestamp': now,
            'robot_id': robot_idx,
            'alert_type': alert_type,
            'severity': severity,
            'message': message,
            'value': value,
            'threshold': threshold,
        }
        self.alert_buffer.append(alert)
        _alert_counter.labels(robot_id=str(robot_idx), alert_type=alert_type).inc()

        out = String()
        out.data = json.dumps(alert)
        self.alert_pub.publish(out)
        self.get_logger().info(f'[{severity.upper()}] {message}')


def main() -> None:
    rclpy.init()
    n = int(os.environ.get('NUM_ROBOTS', '3'))
    start_http_server(8888)
    node = AlertMonitorNode(n)
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
