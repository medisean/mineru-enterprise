Place pre-downloaded MinerU model files in this directory before building
`worker` or `worker-gpu` images.

This directory is copied into the image at:

```text
/opt/mineru-models/
```

Also place the MinerU config file at:

```text
backend/mineru.json
```

It will be copied into the image at:

```text
/root/mineru.json
```

Model files are intentionally ignored by git.

