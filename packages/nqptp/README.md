# nqptp carry

Arch's nqptp 1.2.8-1 recipe (gitlab.archlinux.org packaging, its 0BSD
`LICENSE` retained) for aarch64, as 1.2.8-1.1 so it sorts above ALARM's
1.2.8-1. It stays on 1.2.8 because ALARM's shairport-sync 5.0.4 reads
nqptp's shared memory interface 10, which 1.2.9 replaced with 11.

`nqptp-1.2.8-idle-wakeups.patch` is fedora-aurora's
`nqptp-1.2.9-idle-wakeups.patch` reworked for 1.2.8, whose broadcasting task
walks a single clock table instead of one per client. Upstream's main loop
polls with a 10 ms `select()` timeout, so its SCHED_FIFO thread woke 100
times a second with no AirPlay session; real-time wakeups run the CPU at full
speed, and an idle AirPlay 2 receiver cost 0.3-1.4 W on Aurora's Macs
(measured on Fedora). The patch sleeps until a packet arrives and wakes for
the broadcasting task only while a clock has sent three Announce messages
without a Follow_Up, the only case in which that task acts.

Measured on an x86_64 Arch build host, nqptp idle in its own network
namespace for 10 s: 965 voluntary context switches unpatched, 0 patched.
`check()` asserts the blocking select and the smi10 interface.

Before merging, an AirPlay 2 receive test is still needed: shairport-sync in
AirPlay 2 mode on a Mac, a sender connected, playback in sync, and the idle
wakeups back to zero after the session ends. Retire the carry when ALARM's
nqptp includes an equivalent upstream fix.
