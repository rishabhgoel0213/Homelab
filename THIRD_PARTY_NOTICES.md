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

## Mach-1 Additive 35B

The local Mach-1 service interoperates with the packed checkpoint published by
Syzygy Research and includes the JavaScript/WebGPU runtime served by Syzygy's
public Mach-1 browser demo on 2026-08-05.

- Model: [SyzygyResearch/Mach-1-Additive-35B](https://huggingface.co/SyzygyResearch/Mach-1-Additive-35B)
- Runtime source: [Syzygy Mach-1 browser demo](https://withsyzygy.com/mach-1)
- Model repository license: Apache License 2.0

The vendored `fzstd` 0.1.1 module is Copyright (c) 2020 Arjun Barrett and is
distributed under the MIT License included in that source file.
