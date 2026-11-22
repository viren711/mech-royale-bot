# ApexMech

A C++20 bot for the Builders Buildathon Mech Royale track. It reads and writes `mechfight/1` JSON lines over standard input and output. The arena data is supplied by the match runner.

Build the submission image from the repository root:

```sh
docker build --platform linux/amd64 -t apexmech .
```

With the official starter kit extracted to `kit/`, run the conformance check in the match sandbox:

```sh
python3 kit/check/check.py --map-dir /arena -- docker run --rm -i \
  --network none --cpus 1 --memory 512m --read-only \
  --tmpfs /tmp:rw,size=64m --user 65534:65534 \
  -v "$PWD/kit/arena:/arena:ro" apexmech
```

The bot uses the C++ standard library. GCC builds it in Docker, and Debian runs the compiled executable.
