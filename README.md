# Raspberry Pi GUI Application

This is a modular GUI application built with `ttkbootstrap` for Raspberry Pi.

## Features
- **Theme Selection**: Change the look and feel of the app dynamically.
- **Camera Feed**: Real-time video display using OpenCV.
- **Modular Design**: Separate files for camera and theme logic.

## Prerequisites
- Python 3.x
- A webcam or Raspberry Pi Camera Module

## Installation

1. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

1. Run the main application:
   ```bash
   python main.py
   ```

2. Use the **Theme Selector** in the sidebar to change themes.
3. Click **Start Camera** to view the video feed.

## Files
- `main.py`: Main application script.
- `camera_module.py`: Handles camera interactions.
- `theme_module.py`: Handles theme changes.
