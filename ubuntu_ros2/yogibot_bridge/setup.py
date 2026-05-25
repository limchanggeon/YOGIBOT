from setuptools import find_packages, setup

package_name = "yogibot_bridge"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/bringup.launch.py"]),
    ],
    install_requires=["setuptools", "paho-mqtt>=2.1"],
    zip_safe=True,
    maintainer="yogibot",
    maintainer_email="csc.mokwon.boot@gmail.com",
    description="가상 TurtleBot3 시뮬레이터 + MQTT 브리지",
    license="MIT",
    entry_points={
        "console_scripts": [
            "robot_simulator = yogibot_bridge.robot_simulator:main",
            "mqtt_bridge = yogibot_bridge.mqtt_bridge:main",
        ],
    },
)
