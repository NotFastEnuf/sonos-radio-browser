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

* Docker
* Docker Compose

### Setup

1. Clone or download this repository.
2. Bring up the docker container
   ```
   docker compose up --build -d
   ```
3. Open your browser and visit:

   ```
   http://localhost:5000
   ```

   or, from another device on the same LAN:

   ```
   http://<your-computer-ip>:5000
   ```

### Notes
* Automatic detecton of Sonos speakers is not supported due to restrictions sharing lan with docker container on windows.  Manual IP entry of Sonos speaker has been added.
* Radio streams are provided through the [Radio Browser API](https://www.radio-browser.info/).
* Not all streams are guaranteed to be compatible with Sonos; the backend attempts to relay all stream types using ffmpegs for best compatibility.  
* The project uses Tailwind CSS for a clean and modern UI.

### Credits

This project was **created with the assistance of AI tools**, including code generation and iterative refinement to achieve a functional and intuitive Sonos control interface.

---

**Use responsibly.** This project is intended for personal entertainment and education, non-commercial use only.

### Future Integrations
* Refine favorites catalog
* Test/Add support to search Jamendo API
