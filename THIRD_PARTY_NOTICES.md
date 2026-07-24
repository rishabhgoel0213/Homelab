# Third-party notices

This repository contains independently written integrations with third-party
services. Product and company names belong to their respective owners.

## Instructure Canvas Android

The UMD Canvas bridge in `scripts/canvas-bridge.py` uses the Canvas mobile
verification endpoint and OAuth parameters needed to interoperate with Canvas.
Those protocol details were verified against Instructure's open-source Canvas
Android implementation:

- Project: [instructure/canvas-android](https://github.com/instructure/canvas-android)
- Reference:
  [`MobileVerifyAPI.kt`](https://github.com/instructure/canvas-android/blob/master/libs/login-api-2/src/main/java/com/instructure/loginapi/login/api/MobileVerifyAPI.kt)
- Copyright: Copyright (C) 2020-present Instructure, Inc.
- License of the referenced file: GNU General Public License, version 3

The bridge is an independent Python implementation. It does not contain, link,
or distribute Canvas Android source code or binaries. The names of network
endpoints and request parameters are used solely for interoperability. Canvas
Android remains governed by its own license; this notice does not relicense
this repository.
