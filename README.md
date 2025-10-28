# Sonos Radio Browser

### Overview

This project provides a granular web-based control interface for Sonos speakers, allowing you to:

* Browse and play internet radio streams via the Radio Browser API
* Control playback (play, pause, next, previous)
* Adjust and view live speaker volume
* Mute or unmute your speaker
* View current track metadata and cover art when available

It automatically discovers Sonos speakers on your local network and communicates directly with them using their local API.

### Disclaimer

This software is **not affiliated with, endorsed by, or supported by Sonos, Inc.** All product names and brands are the property of their respective owners.

### Requirements

* Python 3.9 or later
* Flask
* SoCo (Sonos Controller Library)
* Requests
* A local Sonos speaker on the same network

### Setup

1. Clone or download this repository.
2. Init a python virtual environment and install dependencies.
   ```bash
   python -m venv venv
   cd venv
   cd Scripts
   activate
   pip install flask soco requests
   ```
3. Run the backend server:

   ```bash
   python app.py
   ```
4. Open your browser and visit:

   ```
   http://localhost:5000
   ```

   or, from another device on the same LAN:

   ```
   http://<your-computer-ip>:5000
   ```

### Notes

* Radio streams are provided through the [Radio Browser API](https://www.radio-browser.info/).
* Not all streams are guaranteed to be compatible with Sonos; the backend attempts to validate stream types for best compatibility, but MIME type is not fully realized until streaming to the Sonos.  
* The project uses Tailwind CSS for a clean and modern UI.

### Credits

This project was **created with the assistance of AI tools**, including code generation and iterative refinement to achieve a functional and intuitive Sonos control interface.

---

**Use responsibly.** This project is intended for personal entertainment and education, non-commercial use only.

### Future Integrations
* Refine favorites catalog
* Test/Add support to search Jamendo API
* Explore methods to proxy incompatible streams/MIME type
