#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq build-essential clang lld cmake ninja-build pkg-config git python3-venv python3-pip \
  libsdl2-dev glslang-dev glslang-tools spirv-tools libspirv-cross-c-shared-dev libvulkan-dev \
  mesa-vulkan-drivers vulkan-tools libgl1-mesa-dri >/dev/null
clang --version | head -1; cmake --version | head -1
ls /usr/lib/x86_64-linux-gnu/libvulkan_*.so
vulkaninfo --summary 2>/dev/null | grep -E "deviceName|driverName|apiVersion" | head -12
