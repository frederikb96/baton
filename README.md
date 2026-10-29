# baton

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A self-hosted remote for Spotify, controlled from a Garmin watch. A small server container talks to the Spotify Web API; a Connect IQ watch app calls it through the phone.

Work in progress. Planned layout:

- `server/`: the REST API, a small web UI and the Spotify OAuth flow
- `watch/`: the Connect IQ app
- `docs/`: setup and usage
