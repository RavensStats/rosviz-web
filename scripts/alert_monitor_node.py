#!/usr/bin/env python3
"""Monitor robot sensor topics and publish alerts when thresholds are exceeded.

Detects:
  COLLISION        — LaserScan min range below threshold
  VELOCITY_EXCEEDED — Odometry linear/angular velocity above threshold
  CONNECTION_LOSS  — No message received on any topic for a robot within timeout
  LOW_BATTERY      — BatteryState percentage or voltage below threshold
  IMPACT_DETECTED  — IMU horizontal acceleration spike
  TILT_WARNING     — IMU roll/pitch angle exceeds safe limit
  MOTOR_STALL      — Wheel velocity near zero while move command is active
  GEOFENCE_BREACH  — Robot position outside configured bounding box

Publishes:
  /robot_alerts         (std_msgs/String) — one JSON alert per message
  /robot_alerts_history (std_msgs/String) — full ring buffer (50 alerts) every 5s

Exposes Prometheus metrics on :8888 for Grafana scraping.
"""

import json
import math
import os
import pathlib
import signal
import sys
import time
import uuid
from collections import deque

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from prometheus_client import Counter, Gauge, start_http_server
from sensor_msgs.msg import BatteryState, Imu, JointState, LaserScan
from std_msgs.msg import Bool, String

# ── TurtleBot3 footprint radii (centre to furthest corner, metres) ──────
# Burger:    138 mm × 178 mm  → half-diagonal ≈ 0.113 m
# Waffle/Pi: 306 mm × 306 mm  → half-diagonal ≈ 0.216 m
_TB3_RADII: dict[str, float] = {
    'burger':   math.sqrt(0.069**2 + 0.089**2),
    'waffle':   math.sqrt(0.153**2 + 0.153**2),
    'waffle_pi': math.sqrt(0.153**2 + 0.153**2),
}

def _collision_threshold() -> float:
    """Return scan threshold = robot corner radius + safety margin.

    Reads TURTLEBOT3_MODEL from the environment. Falls back to
    ALERT_SCAN_MIN_M if set explicitly, or 0.25 m if the model is unknown.
    """
    if 'ALERT_SCAN_MIN_M' in os.environ:
        return float(os.environ['ALERT_SCAN_MIN_M'])
    model = os.environ.get('TURTLEBOT3_MODEL', '').lower()
    radius = _TB3_RADII.get(model)
    if radius is None:
        return 0.25  # conservative fallback for unknown models
    margin = float(os.environ.get('ALERT_SCAN_MARGIN_M', '0.05'))
    return radius + margin


# ── Prometheus metrics (module-level, shared across all node instances) ──
_alert_counter = Counter(
    'robot_alert_total', 'Total alerts fired', ['robot_id', 'alert_type']
)
_scan_gauge      = Gauge('robot_min_scan_range',    'Minimum laser scan range (m)',       ['robot_id'])
_vel_lin_gauge   = Gauge('robot_velocity_linear',   'Linear velocity X (m/s)',            ['robot_id'])
_vel_ang_gauge   = Gauge('robot_velocity_angular',  'Angular velocity Z (rad/s)',          ['robot_id'])
_bat_pct_gauge   = Gauge('robot_battery_percentage','Battery percentage (0-100)',          ['robot_id'])
_imu_accel_gauge = Gauge('robot_imu_accel_horiz',   'Horizontal acceleration magnitude (m/s²)', ['robot_id'])
_tilt_gauge      = Gauge('robot_tilt_angle_deg',    'Max roll/pitch angle (degrees)',      ['robot_id'])
_geofence_gauge  = Gauge('robot_geofence_status',   'Geofence violation (1=breach, 0=ok)', ['robot_id'])
_auto_stop_gauge   = Gauge('robot_safety_auto_stop_enabled', 'Auto-stop feature enabled (1=on)')
_conn_status_gauge = Gauge('robot_connection_status',       'Connection status (1=ok, 0=lost)',  ['robot_id'])
_stall_gauge       = Gauge('robot_motor_stall_status',      'Motor stall (1=stalling, 0=ok)',    ['robot_id'])
_coll_thresh_gauge = Gauge('robot_collision_threshold',     'Dynamic collision threshold (m)',    ['robot_id'])


class AlertMonitorNode(Node):
    def __init__(self, num_robots: int):
        super().__init__('alert_monitor')
        self.num_robots = num_robots

        # Thresholds (env-overridable)
        self.scan_min_m = _collision_threshold()
        self.scan_reaction_time_s = float(os.environ.get('ALERT_SCAN_REACTION_S', '0.5'))
        self.vel_linear_max = float(os.environ.get('ALERT_VEL_LINEAR_MAX', '0.50'))
        self.vel_angular_max = float(os.environ.get('ALERT_VEL_ANGULAR_MAX', '2.00'))
        self.conn_timeout_s = float(os.environ.get('ALERT_CONN_TIMEOUT_S', '5.0'))
        self.bat_pct_min = float(os.environ.get('ALERT_BATTERY_PCT_MIN', '20.0'))
        self.bat_volt_min = float(os.environ.get('ALERT_BATTERY_VOLT_MIN', '10.5'))
        self.impact_accel_ms2  = float(os.environ.get('ALERT_IMPACT_ACCEL_MS2', '8.0'))
        self.tilt_deg_max      = float(os.environ.get('ALERT_TILT_DEG', '20.0'))
        self.stall_duration_s  = float(os.environ.get('ALERT_STALL_DURATION_S', '2.0'))
        self.geofence_x_min    = float(os.environ.get('ALERT_GEOFENCE_X_MIN', '-5.0'))
        self.geofence_x_max    = float(os.environ.get('ALERT_GEOFENCE_X_MAX',  '5.0'))
        self.geofence_y_min    = float(os.environ.get('ALERT_GEOFENCE_Y_MIN', '-5.0'))
        self.geofence_y_max    = float(os.environ.get('ALERT_GEOFENCE_Y_MAX',  '5.0'))

        # State
        self.auto_stop_enabled: bool = False
        self.alert_buffer: deque = deque(maxlen=50)
        self.active_conditions: set = set()  # string keys: "{robot_idx}:{condition_id}"
        self.clear_times: dict[str, float] = {}
        self.refire_cooldown_s = float(os.environ.get('ALERT_REFIRE_COOLDOWN_S', '10.0'))
        self._history_file = pathlib.Path(
            os.environ.get('ALERT_HISTORY_FILE', '/data/alert_history.json')
        )
        self._load_alert_history()

        for i in range(num_robots):
            _conn_status_gauge.labels(robot_id=str(i)).set(1)
            _stall_gauge.labels(robot_id=str(i)).set(0)
        self.last_msg_time: dict = {}     # robot_idx -> timestamp
        self.last_velocity: dict = {}     # robot_idx -> abs linear velocity (m/s)
        self.real_battery: set = set()    # robot indices with real BatteryState msgs
        self.last_cmd_vel: dict = {}      # robot_idx -> (linear_x, angular_z, timestamp)
        self.stall_start_time: dict = {}  # robot_idx -> time stall began, or None
        # Stagger starting charge so robots show distinct lines on the chart
        self.simulated_battery: dict = {
            i: 95.0 - (i * 5.0) for i in range(num_robots)
        }

        # Publishers
        self.alert_pub = self.create_publisher(String, '/robot_alerts', 10)
        self.history_pub = self.create_publisher(String, '/robot_alerts_history', 1)
        self.auto_stop_status_pub = self.create_publisher(Bool, '/safety_auto_stop_status', 1)
        self.cmd_vel_pubs: dict = {
            i: self.create_publisher(Twist, f'/tb3_{i}/cmd_vel', 10)
            for i in range(num_robots)
        }
        self._publish_auto_stop_status()

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
            self.create_subscription(
                Imu, f'/{ns}/imu',
                lambda m, n=ns, idx=i: self._on_imu(m, n, idx), 10
            )
            self.create_subscription(
                Twist, f'/{ns}/cmd_vel',
                lambda m, n=ns, idx=i: self._on_cmd_vel(m, n, idx), 10
            )
            self.create_subscription(
                JointState, f'/{ns}/joint_states',
                lambda m, n=ns, idx=i: self._on_joint_states(m, n, idx), 10
            )

        # Global subscriptions
        self.create_subscription(Bool, '/safety_auto_stop', self._on_auto_stop_toggle, 1)

        # Timers
        self.create_timer(1.0, self._check_connection_timeouts)
        self.create_timer(1.0, self._update_simulated_battery)
        self.create_timer(5.0, self._publish_history)

        self.get_logger().info(
            f'Alert monitor started for {num_robots} robot(s) — Prometheus on :8888'
        )

    # ── Subscription callbacks ──────────────────────────────────────────────

    def _on_scan(self, msg: LaserScan, ns: str, idx: int) -> None:
        self.last_msg_time[idx] = time.time()

        forward_min = float('inf')
        rear_min = float('inf')
        side_min = float('inf')
        for i, r in enumerate(msg.ranges):
            if not (msg.range_min <= r <= msg.range_max) or math.isnan(r) or math.isinf(r):
                continue
            angle = msg.angle_min + i * msg.angle_increment
            # Normalise to (-π, π]
            angle = (angle + math.pi) % (2 * math.pi) - math.pi
            if abs(angle) <= math.pi / 4:           # forward ±45°
                forward_min = min(forward_min, r)
            elif abs(angle) >= 3 * math.pi / 4:     # rear ±45°
                rear_min = min(rear_min, r)
            else:                                    # sides
                side_min = min(side_min, r)

        overall_min = min(forward_min, rear_min, side_min)
        _scan_gauge.labels(robot_id=str(idx)).set(overall_min)

        cmd = self.last_cmd_vel.get(idx)
        speed     = abs(cmd[0]) if cmd is not None else 0.0
        reversing = cmd is not None and cmd[0] < -0.05
        turning   = cmd is not None and abs(cmd[1]) > 0.1

        crit_thresh = self.scan_min_m + speed * self.scan_reaction_time_s
        warn_thresh = 2.0 * crit_thresh
        _coll_thresh_gauge.labels(robot_id=str(idx)).set(crit_thresh)

        # ── Forward ±45° ──────────────────────────────────────────────
        if forward_min < crit_thresh:
            self._clear_alert(idx, 'COLLISION_FWD_WARN')
            self._fire_alert(idx, 'COLLISION', 'critical',
                f'{ns}: obstacle ahead at {forward_min:.2f} m',
                forward_min, crit_thresh, cond='COLLISION_FWD_CRIT')
        elif forward_min < warn_thresh:
            self._clear_alert(idx, 'COLLISION_FWD_CRIT')
            self._fire_alert(idx, 'COLLISION', 'warning',
                f'{ns}: obstacle ahead at {forward_min:.2f} m',
                forward_min, warn_thresh, cond='COLLISION_FWD_WARN')
        else:
            self._clear_alert(idx, 'COLLISION_FWD_CRIT', 'COLLISION_FWD_WARN')

        # ── Rear ±45° ─────────────────────────────────────────────────
        if rear_min < crit_thresh:
            severity = 'critical' if reversing else 'warning'
            self._clear_alert(idx, 'COLLISION_REAR_WARN')
            self._fire_alert(idx, 'COLLISION', severity,
                f'{ns}: obstacle behind at {rear_min:.2f} m',
                rear_min, crit_thresh, cond='COLLISION_REAR_CRIT')
        elif rear_min < warn_thresh and reversing:
            self._clear_alert(idx, 'COLLISION_REAR_CRIT')
            self._fire_alert(idx, 'COLLISION', 'warning',
                f'{ns}: obstacle behind at {rear_min:.2f} m',
                rear_min, warn_thresh, cond='COLLISION_REAR_WARN')
        else:
            self._clear_alert(idx, 'COLLISION_REAR_CRIT', 'COLLISION_REAR_WARN')

        # ── Sides — critical if turning (sweeping into wall), else warning ──
        if side_min < self.scan_min_m:
            side_sev = 'critical' if turning else 'warning'
            self._fire_alert(idx, 'COLLISION', side_sev,
                f'{ns}: obstacle nearby at {side_min:.2f} m',
                side_min, self.scan_min_m, cond='COLLISION_SIDE')
        else:
            self._clear_alert(idx, 'COLLISION_SIDE')

    def _on_odom(self, msg: Odometry, ns: str, idx: int) -> None:
        self.last_msg_time[idx] = time.time()
        lin_x = msg.twist.twist.linear.x
        ang_z = msg.twist.twist.angular.z
        self.last_velocity[idx] = abs(lin_x)
        _vel_lin_gauge.labels(robot_id=str(idx)).set(abs(lin_x))
        _vel_ang_gauge.labels(robot_id=str(idx)).set(abs(ang_z))
        if abs(lin_x) > self.vel_linear_max or abs(ang_z) > self.vel_angular_max:
            label = (f'linear vel {lin_x:.2f} m/s' if abs(lin_x) > self.vel_linear_max
                     else f'angular vel {ang_z:.2f} rad/s')
            self._fire_alert(
                idx, 'VELOCITY_EXCEEDED', 'warning',
                f'{ns}: {label}',
                max(abs(lin_x), abs(ang_z)), max(self.vel_linear_max, self.vel_angular_max)
            )
        else:
            self._clear_alert(idx, 'VELOCITY_EXCEEDED')

        # GEOFENCE_BREACH
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y
        in_bounds = (
            self.geofence_x_min <= x <= self.geofence_x_max and
            self.geofence_y_min <= y <= self.geofence_y_max
        )
        _geofence_gauge.labels(robot_id=str(idx)).set(0 if in_bounds else 1)
        if not in_bounds:
            self._fire_alert(
                idx, 'GEOFENCE_BREACH', 'critical',
                f'{ns}: out of bounds ({x:.1f}, {y:.1f})',
                math.sqrt(x * x + y * y), 0.0
            )
        else:
            self._clear_alert(idx, 'GEOFENCE_BREACH')

    def _on_battery(self, msg: BatteryState, ns: str, idx: int) -> None:
        self.last_msg_time[idx] = time.time()
        # sensor_msgs/BatteryState.percentage is 0.0–1.0
        pct = msg.percentage * 100.0
        volt = msg.voltage
        # Real data arrived — sync simulation and stop draining for this robot
        self.real_battery.add(idx)
        self.simulated_battery[idx] = pct
        _bat_pct_gauge.labels(robot_id=str(idx)).set(pct)
        if pct < self.bat_pct_min or volt < self.bat_volt_min:
            label = (f'battery at {pct:.0f}%' if pct < self.bat_pct_min
                     else f'voltage at {volt:.1f} V')
            self._fire_alert(
                idx, 'LOW_BATTERY', 'warning',
                f'{ns}: {label}', pct, self.bat_pct_min
            )
        else:
            self._clear_alert(idx, 'LOW_BATTERY')

    def _on_imu(self, msg: Imu, ns: str, idx: int) -> None:
        self.last_msg_time[idx] = time.time()
        ax = msg.linear_acceleration.x
        ay = msg.linear_acceleration.y
        horiz = math.sqrt(ax * ax + ay * ay)
        _imu_accel_gauge.labels(robot_id=str(idx)).set(horiz)
        if horiz > self.impact_accel_ms2:
            self._fire_alert(
                idx, 'IMPACT_DETECTED', 'warning',
                f'{ns}: impact {horiz:.1f} m/s²',
                horiz, self.impact_accel_ms2
            )
        else:
            self._clear_alert(idx, 'IMPACT_DETECTED')
        # TILT_WARNING: quaternion → roll/pitch
        qx = msg.orientation.x
        qy = msg.orientation.y
        qz = msg.orientation.z
        qw = msg.orientation.w
        sinr = 2.0 * (qw * qx + qy * qz)
        cosr = 1.0 - 2.0 * (qx * qx + qy * qy)
        roll = math.atan2(sinr, cosr)
        sinp = 2.0 * (qw * qy - qz * qx)
        pitch = math.copysign(math.pi / 2, sinp) if abs(sinp) >= 1 else math.asin(sinp)
        tilt_deg = math.degrees(max(abs(roll), abs(pitch)))
        _tilt_gauge.labels(robot_id=str(idx)).set(tilt_deg)
        if tilt_deg > self.tilt_deg_max:
            self._fire_alert(
                idx, 'TILT_WARNING', 'critical',
                f'{ns}: tilt {tilt_deg:.1f}°',
                tilt_deg, self.tilt_deg_max
            )
        else:
            self._clear_alert(idx, 'TILT_WARNING')

    def _on_cmd_vel(self, msg: Twist, ns: str, idx: int) -> None:
        self.last_cmd_vel[idx] = (msg.linear.x, msg.angular.z, time.time())

    _WHEEL_JOINTS = {'wheel_left_joint', 'wheel_right_joint'}

    def _on_joint_states(self, msg: JointState, ns: str, idx: int) -> None:
        self.last_msg_time[idx] = time.time()
        cmd = self.last_cmd_vel.get(idx)
        if cmd is None:
            return
        lin_x, ang_z, cmd_time = cmd
        if abs(lin_x) < 0.05 and abs(ang_z) < 0.05:
            self.stall_start_time[idx] = None
            return
        if time.time() - cmd_time > 1.0:  # stale command
            return
        wheel_vels = [
            abs(msg.velocity[i])
            for i, name in enumerate(msg.name)
            if name in self._WHEEL_JOINTS and i < len(msg.velocity)
        ]
        if not wheel_vels:
            return
        max_vel = max(wheel_vels)
        if max_vel < 0.1:
            if self.stall_start_time.get(idx) is None:
                self.stall_start_time[idx] = time.time()
            elif time.time() - self.stall_start_time[idx] >= self.stall_duration_s:
                _stall_gauge.labels(robot_id=str(idx)).set(1)
                self._fire_alert(
                    idx, 'MOTOR_STALL', 'warning',
                    f'{ns}: wheels stalled (vel {max_vel:.3f} rad/s)',
                    max_vel, 0.1
                )
        else:
            self.stall_start_time[idx] = None
            _stall_gauge.labels(robot_id=str(idx)).set(0)
            self._clear_alert(idx, 'MOTOR_STALL')

    # ── Timer callbacks ─────────────────────────────────────────────────────

    def _update_simulated_battery(self) -> None:
        """Drain simulated battery for robots that don't publish BatteryState.

        Drain rate: 0.008 %/s at rest + 0.04 * velocity %/s when moving.
        At rest this takes ~3.5 hours to drain from 95 % to 0 %.
        At max velocity (0.5 m/s) total drain is 0.028 %/s (~60 min from full).
        """
        for idx in range(self.num_robots):
            if idx in self.real_battery:
                continue
            vel = self.last_velocity.get(idx, 0.0)
            drain = 0.008 + vel * 0.04
            self.simulated_battery[idx] = max(0.0, self.simulated_battery[idx] - drain)
            pct = self.simulated_battery[idx]
            _bat_pct_gauge.labels(robot_id=str(idx)).set(pct)
            if pct < self.bat_pct_min:
                self._fire_alert(
                    idx, 'LOW_BATTERY', 'warning',
                    f'tb3_{idx}: battery at {pct:.0f}%',
                    pct, self.bat_pct_min
                )
            else:
                self._clear_alert(idx, 'LOW_BATTERY')

    def _check_connection_timeouts(self) -> None:
        now = time.time()
        for idx in range(self.num_robots):
            elapsed = now - self.last_msg_time.get(idx, now)
            if elapsed > self.conn_timeout_s:
                _conn_status_gauge.labels(robot_id=str(idx)).set(0)
                self._fire_alert(
                    idx, 'CONNECTION_LOSS', 'critical',
                    f'tb3_{idx}: no data for {elapsed:.0f}s',
                    elapsed, self.conn_timeout_s
                )
            else:
                _conn_status_gauge.labels(robot_id=str(idx)).set(1)
                self._clear_alert(idx, 'CONNECTION_LOSS')

    def _load_alert_history(self) -> None:
        try:
            if self._history_file.exists():
                data = json.loads(self._history_file.read_text())
                self.alert_buffer.extend(data[-self.alert_buffer.maxlen:])
                self.get_logger().info(
                    f'Loaded {len(self.alert_buffer)} alerts from {self._history_file}'
                )
        except Exception as e:
            self.get_logger().warn(f'Could not load alert history: {e}')

    def _save_alert_history(self) -> None:
        try:
            self._history_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._history_file.with_suffix('.tmp')
            tmp.write_text(json.dumps(list(self.alert_buffer)))
            tmp.replace(self._history_file)   # atomic on Linux (POSIX rename)
        except Exception as e:
            self.get_logger().warn(f'Could not save alert history: {e}')

    def _publish_history(self) -> None:
        msg = String()
        msg.data = json.dumps(list(self.alert_buffer))
        self.history_pub.publish(msg)
        self._save_alert_history()

    # ── Auto-stop toggle ────────────────────────────────────────────────────

    def _publish_auto_stop_status(self) -> None:
        msg = Bool()
        msg.data = self.auto_stop_enabled
        self.auto_stop_status_pub.publish(msg)
        _auto_stop_gauge.set(1 if self.auto_stop_enabled else 0)

    def _on_auto_stop_toggle(self, msg: Bool) -> None:
        self.auto_stop_enabled = msg.data
        self._publish_auto_stop_status()
        self.get_logger().info(f'Auto-stop {"enabled" if msg.data else "disabled"}')

    # ── Alert dispatch ──────────────────────────────────────────────────────

    def _clear_alert(self, robot_idx: int, *cond_ids: str) -> None:
        for cid in cond_ids:
            key = f"{robot_idx}:{cid}"
            self.active_conditions.discard(key)
            self.clear_times[key] = time.time()

    def _fire_alert(
        self,
        robot_idx: int,
        alert_type: str,
        severity: str,
        message: str,
        value: float,
        threshold: float,
        *,
        cond: str | None = None,
    ) -> None:
        key = f"{robot_idx}:{cond or alert_type}"
        if key in self.active_conditions:
            return
        elapsed = time.time() - self.clear_times.get(key, 0)
        if elapsed < self.refire_cooldown_s:
            return
        self.active_conditions.add(key)

        if self.auto_stop_enabled and severity == 'critical':
            stop = Twist()
            pub = self.cmd_vel_pubs.get(robot_idx)
            if pub:
                pub.publish(stop)

        now = time.time()
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

    def _shutdown(signum, frame):
        node.get_logger().info('Shutdown signal received — saving alert history')
        node._save_alert_history()
        node.destroy_node()
        rclpy.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
