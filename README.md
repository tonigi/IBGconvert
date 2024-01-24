# IBG convert

Reverse-engineered converter for a long-lost IBG image format. 

To my knowledge it is only used in a "Invitation au voyage" CD-ROM
related to this exhibition:

> Invitation au voyage. La photographie humaniste française et la
> photogrphie neoréaliste italienne. Napoli, Castel Sant'Elmo, 23
> Gennaio - 7 Novembre, 1993.

The format appears to be a BMP V3 format with a different signature. 
Regardless of the [header](https://docs.microsoft.com/it-it/windows/win32/api/wingdi/ns-wingdi-bitmapinfo),
however, the data section appears to be
compressed with a non-standard algorithm analog to PackBits.
All of the available examples are 8-bit RGB indexed.
The format seems related to a Windows 3.1 DLL named `ibg.dll`. 

The reverse-engineered algorithm decodes to an equivalent indexed PNG
using the `pypng` module. Succeeds with 950/959 files, so that there
may still be some edge cases left. However, the missing files are not decoded
by the native application, either.

