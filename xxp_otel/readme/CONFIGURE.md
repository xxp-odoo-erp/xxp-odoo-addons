By default, the module is disabled.

The module reads its parameters from the `[options]` section of the Odoo configuration
file (`odoo.conf` or the `--config` option). After you change a parameter, restart
Odoo.

The module does not use the `OTEL_*` and `XXP_OTEL_*` environment variables. When the
SDK starts, the module removes these variables for a short time. Thus, the exporter
does not read them.

## Minimum configuration

```ini
[options]
otel_enabled = true
otel_service_name = odoo
otel_otlp_endpoint = http://otel-collector:4318
otel_otlp_headers = Authorization=Basic <base64>
otel_otlp_timeout = 5
```

`otel_otlp_endpoint` is the base URL for OTLP ingestion. Do not add a slash at the
end. The module adds `/v1/traces` and `/v1/logs` to the base URL. Some backends use a
path prefix, for example `http://<host>:<port>/<prefix>`. Refer to the documentation
of your backend.

`otel_otlp_headers` contains the authentication headers that your backend requires.

For production, set `otel_otlp_timeout = 5`. This value is the maximum time that one
send operation holds the export thread. This value is also a part of the worker stop
time.

The default values are applicable to production:

- The module samples 10% of traces (`parentbased_traceidratio`, `0.1`).
- The module exports log records that it selects by prefix only from the `WARNING`
  level.
- The module does not write request parameters to spans.
- The module does not trace the `/websocket` and `/longpolling` routes.

## Full configuration example

```ini
[options]
otel_trace_http = true
otel_trace_rpc = true
otel_trace_routes = /web/dataset,/web/login
otel_trace_exclude_routes = /websocket,/longpolling,/web/static,/web/assets
otel_traces_sampler = parentbased_traceidratio
otel_traces_sampler_arg = 0.1
otel_capture_request_params = false
otel_log_level = INFO
otel_log_prefixes = odoo.addons.my_integration,odoo.addons.my_webhook
otel_log_prefix_level = WARNING
otel_max_message_length = 32768
otel_max_attribute_length = 32768
otel_max_collection_items = 100
otel_max_depth = 6
otel_max_event_bytes = 262144
otel_log_queue_max_bytes = 33554432
otel_log_max_queue_size = 2048
otel_log_max_export_batch_size = 64
otel_log_schedule_delay = 200
otel_redact_keys = private_key,signature
otel_otlp_traces_endpoint = http://otel-collector:4318/v1/traces
otel_otlp_logs_endpoint = http://otel-collector:4318/v1/logs
otel_otlp_headers = Authorization=Basic <base64>
otel_otlp_timeout = 5
```

## Parameters

### Connection

| Parameter                   | Default                 | Description                                               |
| --------------------------- | ----------------------- | --------------------------------------------------------- |
| `otel_enabled`              | `false`                 | Enables the module.                                       |
| `otel_service_name`         | `odoo`                  | The `service.name` resource attribute.                    |
| `otel_otlp_endpoint`        | `http://localhost:4318` | The base URL for OTLP/HTTP ingestion.                     |
| `otel_otlp_traces_endpoint` | empty                   | The URL for traces. It replaces the base URL for traces.  |
| `otel_otlp_logs_endpoint`   | empty                   | The URL for logs. It replaces the base URL for logs.      |
| `otel_otlp_headers`         | empty                   | HTTP headers as a comma-separated list of `key=value`.    |
| `otel_otlp_timeout`         | `10`                    | The time limit of one send operation, in seconds.         |

### Traces

| Parameter                     | Default                    | Description                                                |
| ----------------------------- | -------------------------- | ---------------------------------------------------------- |
| `otel_trace_http`             | `true`                     | Creates a server span for each incoming HTTP request.      |
| `otel_trace_rpc`              | `true`                     | Adds `odoo.model` and `odoo.method` to JSON-RPC spans.     |
| `otel_trace_routes`           | empty                      | Route prefixes to trace. If empty, the module traces all.  |
| `otel_trace_exclude_routes`   | `/websocket,/longpolling`  | Route prefixes that the module does not trace.             |
| `otel_traces_sampler`         | `parentbased_traceidratio` | The trace sampler.                                         |
| `otel_traces_sampler_arg`     | `0.1`                      | The sample ratio, from `0.0` to `1.0`.                     |
| `otel_capture_request_params` | `false`                    | Writes request parameters to spans.                        |

`otel_traces_sampler` accepts these values:

- `always_on`
- `always_off`
- `traceidratio`
- `parentbased_always_on`
- `parentbased_always_off`
- `parentbased_traceidratio`

If the value is unknown, the module uses `parentbased_always_on`. The `parentbased_*`
samplers use the decision of the caller system if the caller sends a `traceparent`
header.

`otel_trace_routes` limits HTTP traces to a list of route prefixes. If the value is
empty, the module traces all requests.

`otel_trace_exclude_routes` removes routes from tracing. This list has priority over
`otel_trace_routes`.

**Note:** Your value of `otel_trace_exclude_routes` replaces the default value. Thus,
add `/websocket` and `/longpolling` to your list.

The module compares a prefix with a route at the `/` boundary. For example, `/web`
matches `/web/login`, but `/web` does not match `/webhook`. The module compares the
prefix with the Werkzeug route pattern and with the real path.

### Request parameters

By default, `otel_capture_request_params` is `false`. If you set it to `true`, the
module writes the parsed request parameters to the `odoo.request.params` span
attribute. The parameters include:

- The query string.
- The route arguments.
- The JSON-RPC `params`, with `args` and `kwargs`.

The module does not read the raw HTTP body.

The attribute is one valid JSON string. Its maximum size is
`otel_max_attribute_length` bytes in UTF-8. The module redacts secret keys in the
attribute with the same rules as for logs. The module writes the attribute only for
recorded spans. Thus, the module does not collect parameters for requests that the
sampler does not select.

### Logs

| Parameter               | Default   | Description                                                      |
| ----------------------- | --------- | ---------------------------------------------------------------- |
| `otel_log_level`        | `INFO`    | The minimum level for records with `otel_event`.                 |
| `otel_log_prefixes`     | empty     | Logger name prefixes, as a comma-separated list.                 |
| `otel_log_prefix_level` | `WARNING` | The minimum level for records that the module selects by prefix. |
| `otel_redact_keys`      | empty     | More keys to redact. The module adds them to the default list.   |

The `otel_log_prefix_level` filter does not apply to records with `otel_event`. To
export `INFO` records by prefix, set `otel_log_prefix_level = INFO`.

The default list of keys to redact:

```text
authorization, cookie, password, passwd, token,
api_key, apikey, secret, session_id, sessionid
```

## Size and memory limits

The module sanitizes each exported event one time, in the OpenTelemetry handler. The
module does this only if it will send the record. Thus, the record level must pass the
filter, and the export must not be in pause.

| Parameter                        | Default            | Minimum   |
| -------------------------------- | ------------------ | --------- |
| `otel_max_event_bytes`           | `262144` (256 KB)  | `1024`    |
| `otel_max_depth`                 | `6`                | `1`       |
| `otel_max_attribute_length`      | `32768`            | `256`     |
| `otel_max_collection_items`      | `100`              | `1`       |
| `otel_max_message_length`        | `32768`            | `256`     |
| `otel_log_queue_max_bytes`       | `33554432` (32 MB) | `1048576` |
| `otel_log_max_queue_size`        | `2048`             | `1`       |
| `otel_log_max_export_batch_size` | `64`               | `1`       |
| `otel_log_schedule_delay`        | `200` (ms)         | `50`      |

- `otel_max_event_bytes` is the total size of one event in UTF-8 bytes. The size
  includes JSON escape characters. The module fills the budget in this sequence: the
  message text, the exception, the structured metadata and `odoo.capture`. A Cyrillic
  character uses 2 bytes. An emoji uses 4 bytes.
- `otel_max_depth` is the maximum nesting depth. At a deeper level, the module writes
  `"<max-depth>"`.
- `otel_max_attribute_length` and `otel_max_collection_items` are the limits for usual
  structured metadata. The event budget is the only limit for the arguments and the
  result that `observe_method` captures. Thus, the module keeps an API response of
  100 KB fully.
- `otel_max_message_length` is the limit for the message text and for the exception
  stack trace.
- `otel_log_queue_max_bytes` is the maximum size of log data in the queue and in the
  current send operation, for one process. If the collector is slow or does not
  respond, the module discards new records. It does not remove old records. The module
  writes a warning about the number of discarded records a maximum of one time each
  minute.
- `otel_log_max_queue_size` and `otel_log_max_export_batch_size` are the limits of the
  queue and of the batch, in records. The module also divides a batch into OTLP
  requests of a maximum of 4 MB.
- `otel_log_schedule_delay` is the interval between two send operations if the queue
  has fewer records than `otel_log_max_export_batch_size`. A short interval keeps fewer
  large events in memory. With a continuous flow of logs, one process sends a maximum
  of 5 requests each second.

### Memory estimate

If the collector is not available, one worker can use this quantity of memory for
telemetry:

- `otel_log_queue_max_bytes`.
- Plus one serialized request (a maximum of 4 MB).
- Plus the spans in the queue (a maximum of 2048 spans).

With the default values, 12 workers can use approximately 450 MB in the worst case. If
the collector operates correctly, the queue is almost empty.
