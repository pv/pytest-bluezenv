#!/bin/sh
set -e

if [ ! -d "${MESON_DIST_ROOT}" ]; then
    echo "error: MESON_DIST_ROOT not valid"
    exit 1
fi

cd "${MESON_DIST_ROOT}"
for f in subprojects/*/; do
    rm -rf "$f/.git/"
done

tar cf "tmpdist.tar" \
    subprojects/bluez/meson.build \
    subprojects/bluez/doc/*.config \
    subprojects/bluez/doc/test-runner.rst \
    subprojects/bluez/AUTHORS \
    subprojects/bluez/COPYING* \
    subprojects/bluez/emulator/*.h \
    subprojects/bluez/emulator/main.c \
    subprojects/bluez/emulator/serial.c \
    subprojects/bluez/emulator/server.c \
    subprojects/bluez/emulator/vhci.c \
    subprojects/bluez/emulator/btdev.c \
    subprojects/bluez/emulator/bthost.c \
    subprojects/bluez/emulator/smp.c \
    subprojects/bluez/emulator/phy.c \
    subprojects/bluez/emulator/le.c \
    subprojects/bluez/monitor/*.h \
    subprojects/bluez/src/eir.h \
    subprojects/bluez/src/shared/ad.c \
    subprojects/bluez/src/shared/ad.h \
    subprojects/bluez/src/shared/crypto.c \
    subprojects/bluez/src/shared/crypto.h \
    subprojects/bluez/src/shared/ecc.c \
    subprojects/bluez/src/shared/ecc.h \
    subprojects/bluez/src/shared/queue.c \
    subprojects/bluez/src/shared/queue.h \
    subprojects/bluez/src/shared/log.c \
    subprojects/bluez/src/shared/log.h \
    subprojects/bluez/src/shared/util.c \
    subprojects/bluez/src/shared/util.h \
    subprojects/bluez/src/shared/io-mainloop.c \
    subprojects/bluez/src/shared/io.h \
    subprojects/bluez/src/shared/tester.h \
    subprojects/bluez/src/shared/timeout-mainloop.c \
    subprojects/bluez/src/shared/timeout.h \
    subprojects/bluez/src/shared/mainloop.c \
    subprojects/bluez/src/shared/mainloop.h \
    subprojects/bluez/src/shared/mainloop-notify.c \
    subprojects/bluez/src/shared/mainloop-notify.h \
    subprojects/bluez/lib/bluetooth/bluetooth.c \
    subprojects/bluez/lib/bluetooth/bluetooth.h \
    subprojects/bluez/lib/bluetooth/hci.h \
    subprojects/bluez/lib/bluetooth/hci_lib.h \
    subprojects/bluez/lib/bluetooth/sdp.h \
    subprojects/bluez/lib/bluetooth/uuid.c \
    subprojects/bluez/lib/bluetooth/uuid.h \
    subprojects/bluez/tools/*.h \
    subprojects/bluez/tools/test-runner.c
rm -rf subprojects/bluez
tar xf tmpdist.tar
rm -f tmpdist.tar
