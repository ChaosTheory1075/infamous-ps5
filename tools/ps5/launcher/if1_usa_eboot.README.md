# if1_usa_eboot.inc (not in this repository)

`installer.c` includes `if1_usa_eboot.inc`: a C array holding a binary patch (UDP1 format) that turns the decrypted
USA inFAMOUS executable (BCUS98119, v1.00 or v2.00) into the decrypted Europe one (BCES00220) that the game build
is made from. The patch contains bytes of the game's executable, so it is **not distributed in source form**.

Make it yourself from your own two dumps, with the sources in `if1_usa/`:

```bash
cc -O2 -o udelta_enc if1_usa/udelta_enc.c
mkdir -p usa/USRDIR eu/USRDIR
cp <decrypted USA EBOOT.elf> usa/USRDIR/EBOOT.elf
cp <decrypted Europe EBOOT.elf> eu/USRDIR/EBOOT.elf
echo USRDIR/EBOOT.elf > eboot.lst
./udelta_enc usa eu eboot.lst eboot.udp
python3 if1_usa/gen_inc.py eboot.udp if1_usa_eboot.inc
```

`if1_usa/udelta_dec.c` applies such a patch on a PC (`udelta_dec <usa dir> <out dir> eboot.udp`); the installer
applies it with its own `inst_udp1()`.
