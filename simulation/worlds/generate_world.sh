#!/bin/bash

set -euo pipefail

NUM_ROBOTS=${1:-3}
OUTPUT_FILE=${2:-/tmp/turtlebot3_world.generated.sdf}

mkdir -p "$(dirname "$OUTPUT_FILE")"

cat >"$OUTPUT_FILE" <<'EOF'
<?xml version="1.0" ?>
<sdf version="1.8">
  <world name="turtlebot3_world">

    <physics name="fast" type="ignored">
      <max_step_size>0.004</max_step_size>
      <real_time_factor>1.0</real_time_factor>
      <real_time_update_rate>250</real_time_update_rate>
    </physics>

    <plugin filename="ignition-gazebo-physics-system"
            name="ignition::gazebo::systems::Physics"/>
    <plugin filename="ignition-gazebo-scene-broadcaster-system"
            name="ignition::gazebo::systems::SceneBroadcaster"/>
    <plugin filename="ignition-gazebo-user-commands-system"
            name="ignition::gazebo::systems::UserCommands"/>
    <plugin filename="libignition-gazebo-sensors-system.so"
            name="ignition::gazebo::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <plugin filename="libignition-gazebo-imu-system.so"
            name="ignition::gazebo::systems::Imu"/>
    <plugin filename="libignition-gazebo-contact-system.so"
            name="ignition::gazebo::systems::Contact"/>

    <light type="directional" name="sun">
      <cast_shadows>true</cast_shadows>
      <pose>0 0 10 0 0 0</pose>
      <diffuse>0.8 0.8 0.8 1</diffuse>
      <specular>0.2 0.2 0.2 1</specular>
      <direction>-0.5 0.1 -0.9</direction>
    </light>

    <model name="ground_plane">
      <static>true</static>
      <link name="link">
        <collision name="collision">
          <geometry><plane><normal>0 0 1</normal><size>100 100</size></plane></geometry>
        </collision>
        <visual name="visual">
          <geometry><plane><normal>0 0 1</normal><size>100 100</size></plane></geometry>
          <material>
            <ambient>0.8 0.8 0.8 1</ambient>
            <diffuse>0.8 0.8 0.8 1</diffuse>
          </material>
        </visual>
      </link>
    </model>

    <model name="wall_front">
      <static>true</static>
      <pose>2 0 0.25 0 0 0</pose>
      <link name="link">
        <collision name="c"><geometry><box><size>0.1 4 0.5</size></box></geometry></collision>
        <visual name="v"><geometry><box><size>0.1 4 0.5</size></box></geometry>
          <material><ambient>0.6 0.3 0.1 1</ambient><diffuse>0.6 0.3 0.1 1</diffuse></material>
        </visual>
      </link>
    </model>
    <model name="wall_back">
      <static>true</static>
      <pose>-2 0 0.25 0 0 0</pose>
      <link name="link">
        <collision name="c"><geometry><box><size>0.1 4 0.5</size></box></geometry></collision>
        <visual name="v"><geometry><box><size>0.1 4 0.5</size></box></geometry>
          <material><ambient>0.6 0.3 0.1 1</ambient><diffuse>0.6 0.3 0.1 1</diffuse></material>
        </visual>
      </link>
    </model>
    <model name="wall_left">
      <static>true</static>
      <pose>0 2 0.25 0 0 1.5708</pose>
      <link name="link">
        <collision name="c"><geometry><box><size>0.1 4 0.5</size></box></geometry></collision>
        <visual name="v"><geometry><box><size>0.1 4 0.5</size></box></geometry>
          <material><ambient>0.6 0.3 0.1 1</ambient><diffuse>0.6 0.3 0.1 1</diffuse></material>
        </visual>
      </link>
    </model>
    <model name="wall_right">
      <static>true</static>
      <pose>0 -2 0.25 0 0 1.5708</pose>
      <link name="link">
        <collision name="c"><geometry><box><size>0.1 4 0.5</size></box></geometry></collision>
        <visual name="v"><geometry><box><size>0.1 4 0.5</size></box></geometry>
          <material><ambient>0.6 0.3 0.1 1</ambient><diffuse>0.6 0.3 0.1 1</diffuse></material>
        </visual>
      </link>
    </model>

    <model name="box1">
      <static>true</static>
      <pose>1 1 0.25 0 0 0</pose>
      <link name="link">
        <collision name="c"><geometry><box><size>0.5 0.5 0.5</size></box></geometry></collision>
        <visual name="v"><geometry><box><size>0.5 0.5 0.5</size></box></geometry>
          <material><ambient>0.2 0.2 0.8 1</ambient><diffuse>0.2 0.2 0.8 1</diffuse></material>
        </visual>
      </link>
    </model>
    <model name="cyl1">
      <static>true</static>
      <pose>-1 0.5 0.25 0 0 0</pose>
      <link name="link">
        <collision name="c"><geometry><cylinder><radius>0.3</radius><length>0.5</length></cylinder></geometry></collision>
        <visual name="v"><geometry><cylinder><radius>0.3</radius><length>0.5</length></cylinder></geometry>
          <material><ambient>0.8 0.2 0.2 1</ambient><diffuse>0.8 0.2 0.2 1</diffuse></material>
        </visual>
      </link>
    </model>
EOF

for ((i = 0; i < NUM_ROBOTS; i++)); do
    x=$(( (i % 3) - 1 ))
    y=$(( i / 3 ))
    y=$(( y * -1 ))

    yaw="0"
    case $((i % 4)) in
        1) yaw="1.5708" ;;
        2) yaw="3.1416" ;;
        3) yaw="-1.5708" ;;
    esac

    cat >>"$OUTPUT_FILE" <<EOF
    <include>
      <uri>model://turtlebot3_waffle_$i</uri>
      <pose>${x} ${y} 0.01 0 0 ${yaw}</pose>
    </include>
EOF
done

cat >>"$OUTPUT_FILE" <<'EOF'
  </world>
</sdf>
EOF

echo "Generated world: $OUTPUT_FILE ($NUM_ROBOTS robots)"
