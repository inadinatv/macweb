# Synthetic HLS regression media

These are **generated test bars + a 440 Hz sine**, not recordings of a sports
broadcast. Duration: 4 seconds; H.264/AAC, 192×108, 10 fps. Total size is under
300 KB. They are checked in so browser regression tests are offline/reproducible.

- `ts/`: MPEG-TS bytes intentionally named `.jpg`; tests serve `image/jpeg` to
  reproduce the nonstandard segment URI/MIME combination without assuming it is
  a real JPEG. Master and media URLs exercise HTTP redirects and signed queries.
- `fmp4/`: separate init + fragmented MP4 segments, muxed video/audio.
- `range/`: single-file fMP4 + HLS byte ranges (HTTP 206).
- `encrypted/`: AES-128 TS + a **public, synthetic test-only** 16-byte key.
  `key.bin` contains `0123456789abcdef`, is not a credential, and has no production
  purpose. Tests require source headers on both key and segment requests.

Generated with FFmpeg 7.0.2. Base command (change output paths as needed):

```sh
ffmpeg -f lavfi -i testsrc=size=192x108:rate=10 \
  -f lavfi -i sine=frequency=440:sample_rate=22050 \
  -t 4 -c:v libx264 -pix_fmt yuv420p -preset ultrafast -g 10 -sc_threshold 0 \
  -c:a aac -ar 22050 -b:a 24k -f hls -hls_time 1 -hls_playlist_type vod \
  -hls_segment_filename part%d.ts media.m3u8
```

For fMP4 add `-hls_segment_type fmp4 -hls_fmp4_init_filename init.mp4`, use
`.m4s` segment names; for ranges add `-hls_flags single_file`. For encryption use
FFmpeg `-hls_key_info_file` with the test key and IV
`00000000000000000000000000000001`. No production keys are needed or included.
