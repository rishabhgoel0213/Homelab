# Add A Service

## Internal Service

Start the app bound to localhost or a Docker-only network, then add a route:

```bash
just route-add myapp internal http://127.0.0.1:3000
just routes
just switch
```

It will be reachable at:

```text
myapp.internal.therealrishabh.com
```

## Public Service

```bash
just route-add demo public http://127.0.0.1:3000
just routes
just switch
```

It will be reachable at:

```text
demo.therealrishabh.com
```
