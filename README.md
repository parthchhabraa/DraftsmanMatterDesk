# Draftsman MatterDesk

> Asymmetric Tabletop Dashboard Architecture.

MatterDesk is a hardware-accelerated, borderless control matrix designed for Raspberry Pi (32-bit `armhf`). It merges continuous integration (OTA updates) with native Wayland hardware compositing to deliver AirPlay receiver capabilities, CarPlay integration, and strict capacitive power-state management.

## System Architecture

* **Display Compositor:** Wayland / Wayfire (`wf-panel-pi`).
* **Input Handling:** Raw capacitive bridging via `evdev` (FocalTech FT5x06).
* **Receiver Protocol:** `UxPlay` (AirPlay video/audio pipeline).
* **Infotainment Protocol:** `LIVI` interface via Carlinkit (CarPlay).
* **Deployment Pipeline:** Systemd-managed Git continuous integration.

## Hardware Prerequisites

| Component | Specification |
| :--- | :--- |
| Compute | Raspberry Pi (Debian Bookworm 32-bit Legacy Kernel) |
| Display | Waveshare 7-inch Capacitive Touch (DSI / I2C backlight mapped) |
| CarPlay Bridge | Carlinkit CPC200 (CCPA/CCPW) - Required for LIVI |

## Deployment Protocol

The system utilizes an idempotent bootstrap script. Execute directly from the terminal to configure Wayfire, install dependencies, force hardware permissions, and register the OTA daemon.

```bash
git clone [https://github.com/YOUR_USERNAME/Draftsman-MatterDesk.git](https://github.com/YOUR_USERNAME/Draftsman-MatterDesk.git) /home/st6b/matterdesk
cd /home/st6b/matterdesk
chmod +x install.sh
./install.sh