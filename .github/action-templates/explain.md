# Action: explain

You are {{ persona }}. Post a detailed explanation of a recent implementation,
decision, or complex code block on {{ target_type }} #{{ target_number }} using
the marker:

```
EXPLANATION: <topic>
```

Include references to relevant files and lines (e.g. `path/to/file.php:42`).
This post is stored as durable documentation. Sign it with the persona header.
