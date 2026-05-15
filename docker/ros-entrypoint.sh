#!/bin/bash
# =============================================================
#  ROSViz Web — ROS Stack Entrypoint
# =============================================================
#  Launches all ROS 2 / Gazebo processes in a single container.
#  Each process runs in the background; the script waits for all.
#  If any process exits, the container stops.
# =============================================================
set -e
source /opt/ros/humble/setup.bash

# ── Multi-robot config ──
export NUM_ROBOTS=${NUM_ROBOTS:-3}
export IGN_GAZEBO_RESOURCE_PATH="/ros_ws/simulation/models:${IGN_GAZEBO_RESOURCE_PATH:-}"

echo ""
echo "  ┌─────────────────────────────────────────────┐"
echo "  │  ROSViz Web — ROS Stack                     │"
echo "  │  Robots   : $NUM_ROBOTS x TurtleBot3 $TURTLEBOT3_MODEL          │"
echo "  └─────────────────────────────────────────────┘"
echo ""

PIDS=()
cleanup() {
    echo "[entrypoint] Shutting down all processes..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait
    echo "[entrypoint] All processes stopped."
}
trap cleanup SIGINT SIGTERM EXIT

# ── 0. Generate per-robot model folders ──
echo "[entrypoint] Generating $NUM_ROBOTS robot model folders..."
bash /ros_ws/simulation/models/generate_robots.sh "$NUM_ROBOTS"

ROBOTS_XML=""
for i in $(seq 0 $((NUM_ROBOTS-1))); do
    # Spread robots along x axis, alternating sign
    X=$(awk "BEGIN { print ($i - ($NUM_ROBOTS - 1) / 2.0) }")
    ROBOTS_XML="${ROBOTS_XML}
    <include>
      <uri>model://turtlebot3_waffle_$i</uri>
      <pose>$X 0 0.01 0 0 0</pose>
    </include>"
done

# Replace the placeholder in the base template
awk -v r="$ROBOTS_XML" '{gsub(/<!-- ROBOTS_PLACEHOLDER -->/, r); print}' \
    /ros_ws/simulation/worlds/turtlebot3_world_base.sdf \
    > /tmp/turtlebot3_world.sdf

# ── 1. Ignition Gazebo ──
echo "[entrypoint] Starting Ignition Gazebo (headless)..."
ign gazebo -s -r /tmp/turtlebot3_world.sdf &
PIDS+=($!)
sleep 5

# ── 2. ros_gz_bridge — namespaced per robot ──
echo "[entrypoint] Starting ros_gz_bridge..."
BRIDGE_ARGS=""
for i in $(seq 0 $((NUM_ROBOTS-1))); do
    BRIDGE_ARGS="$BRIDGE_ARGS \
        /tb3_$i/cmd_vel@geometry_msgs/msg/Twist]ignition.msgs.Twist \
        /tb3_$i/odom@nav_msgs/msg/Odometry[ignition.msgs.Odometry \
        /tb3_$i/scan@sensor_msgs/msg/LaserScan[ignition.msgs.LaserScan \
        /tb3_$i/imu@sensor_msgs/msg/Imu[ignition.msgs.IMU \
        /tb3_$i/camera/image_raw@sensor_msgs/msg/Image[ignition.msgs.Image \
        /tb3_$i/camera/camera_info@sensor_msgs/msg/CameraInfo[ignition.msgs.CameraInfo \
        /tb3_$i/camera/depth/image_rect_raw@sensor_msgs/msg/Image[ignition.msgs.Image \
        /tb3_$i/camera/depth/camera_info@sensor_msgs/msg/CameraInfo[ignition.msgs.CameraInfo \
        /tb3_$i/camera/depth/image_rect_raw/points@sensor_msgs/msg/PointCloud2[ignition.msgs.PointCloudPacked \
        /tb3_$i/joint_states@sensor_msgs/msg/JointState[ignition.msgs.Model \
        /tb3_$i/scan/points@sensor_msgs/msg/PointCloud2[ignition.msgs.PointCloudPacked"
done
ros2 run ros_gz_bridge parameter_bridge $BRIDGE_ARGS &
PIDS+=($!)
sleep 2

# ── 3. robot_state_publisher — one per robot ──
echo "[entrypoint] Starting robot_state_publisher x $NUM_ROBOTS..."
URDF_FILE="/opt/ros/humble/share/turtlebot3_description/urdf/turtlebot3_${TURTLEBOT3_MODEL}.urdf"
if [ -f "$URDF_FILE" ]; then
    ROBOT_DESC=$(cat "$URDF_FILE")
    for i in $(seq 0 $((NUM_ROBOTS-1))); do
        ros2 run robot_state_publisher robot_state_publisher \
            --ros-args \
            -r __node:=rsp_tb3_$i \
            -r __ns:=/tb3_$i \
            -r /tb3_$i/tf:=/tf \
            -r /tb3_$i/tf_static:=/tf_static \
            -p use_sim_time:=false \
            -p frame_prefix:=tb3_$i/ \
            -p "robot_description:=$ROBOT_DESC" &
        PIDS+=($!)
    done
    sleep 1
else
    echo "[entrypoint] WARNING: URDF not found at $URDF_FILE"
fi

# ── 4. Image compressor (NUM_ROBOTS already exported) ──
echo "[entrypoint] Starting image compressor..."
python3 /ros_ws/scripts/image_compressor.py &
PIDS+=($!)
sleep 1

# ── 4 prime. Muxes for individual view topics ──
echo "[entrypoint] Starting muxes..."
build_inputs() {
    local suffix="$1"
    local out=""
    for i in $(seq 0 $((NUM_ROBOTS-1))); do
        out="$out /tb3_$i/$suffix"
    done
    echo "$out"
}

ros2 run topic_tools mux /selected/scan_points \
    $(build_inputs scan/points) \
    --ros-args -r __node:=mux_scan_points &
PIDS+=($!)

ros2 run topic_tools mux /selected/camera_image \
    $(build_inputs camera/image_raw/compressed) \
    --ros-args -r __node:=mux_camera_image &
PIDS+=($!)

ros2 run topic_tools mux /selected/camera_depth \
    $(build_inputs camera/depth/image_rect_raw/compressed) \
    --ros-args -r __node:=mux_camera_depth &
PIDS+=($!)
sleep 1

# ── Default muxes to robot 0 ──
echo "[entrypoint] Defaulting muxes to tb3_0..."
sleep 2
ros2 service call /mux_scan_points/select topic_tools_interfaces/srv/MuxSelect \
    "{topic: '/tb3_0/scan/points'}" || true
ros2 service call /mux_camera_image/select topic_tools_interfaces/srv/MuxSelect \
    "{topic: '/tb3_0/camera/image_raw/compressed'}" || true
ros2 service call /mux_camera_depth/select topic_tools_interfaces/srv/MuxSelect \
    "{topic: '/tb3_0/camera/depth/image_rect_raw/compressed'}" || true

# ── 5. rosbridge ──
echo "[entrypoint] Starting rosbridge WebSocket on port 9090..."
ros2 launch rosbridge_server rosbridge_websocket_launch.xml &
PIDS+=($!)

echo ""
echo "[entrypoint] All processes started. PIDs: ${PIDS[*]}"
echo ""

wait -n "${PIDS[@]}" 2>/dev/null
EXIT_CODE=$?
echo "[entrypoint] A process exited with code $EXIT_CODE. Stopping container."
exit $EXIT_CODE