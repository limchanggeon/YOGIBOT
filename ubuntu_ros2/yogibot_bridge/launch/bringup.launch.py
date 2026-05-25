"""
robot_simulator + mqtt_bridge 동시 실행.

    ros2 launch yogibot_bridge bringup.launch.py broker_host:=192.168.64.1

broker_host 는 Mac 호스트(브로커) IP. UTM 공유 네트워크에서 보통 게이트웨이 IP.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    broker_host = LaunchConfiguration("broker_host")
    broker_port = LaunchConfiguration("broker_port")
    robot_id = LaunchConfiguration("robot_id")

    return LaunchDescription([
        DeclareLaunchArgument("broker_host", default_value="127.0.0.1",
                              description="Mac 호스트(MQTT 브로커) IP"),
        DeclareLaunchArgument("broker_port", default_value="1883"),
        DeclareLaunchArgument("robot_id", default_value="waffle_01"),

        Node(package="yogibot_bridge", executable="robot_simulator",
             name="robot_simulator", output="screen",
             parameters=[{"robot_id": robot_id}]),

        Node(package="yogibot_bridge", executable="mqtt_bridge",
             name="mqtt_bridge", output="screen",
             parameters=[{"robot_id": robot_id,
                          "broker_host": broker_host,
                          "broker_port": broker_port}]),
    ])
