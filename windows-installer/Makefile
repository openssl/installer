NSISOPTS=/DMAJOR=$(INSTMAJOR) /DMINOR=$(INSTMINOR) /DPATCH=$(INSTPATCH)

!IFDEF INSTBUILD32
NSISOPTS=$(NSISOPTS) /DBUILD32=$(INSTBUILD32)
!ENDIF
!IFDEF INSTBUILD64
NSISOPTS=$(NSISOPTS) /DBUILD64=$(INSTBUILD64)
!ENDIF
!IFDEF INSTLICENSE
NSISOPTS=$(NSISOPTS) /DLICENSE_FILE=$(INSTLICENSE)
!ENDIF
!IFDEF INSTCTX
NSISOPTS=$(NSISOPTS) /DCTX=$(INSTCTX)
!ENDIF

openssl-installer: openssl.nsi
	echo $(NSISOPTS)
	makensis.exe $(NSISOPTS) /V4 .\openssl.nsi

signed-openssl-installer: openssl.nsi
	makecert.exe /n "CN=TestCompany" /r /h 0 /eku "1.3.6.1.5.5.7.3.3,1.3.6.1.4.1.311.10.3.13" /sv testcert.pvk testcert.cer
	pvk2pfx.exe /pvk testcert.pvk /pi testpass /spc testcert.cer /pfx testcert.pfx /po testpass
	makensis.exe $(NSISOPTS) /DSIGN=testcert.pfx /DSIGNPASS=testpass .\openssl.nsi

clean:
	del .\*.exe .\test*.*

