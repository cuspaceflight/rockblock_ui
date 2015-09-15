# rockblock_ui
Simple UI for rockblock USB modem

## Reference Links
* [RockBLOCK dev guide (electrical spec)](http://rockblock.rock7mobile.com/downloads/RockBLOCK-Developer-Guide.pdf)
* [AT command reference](http://rockblock.rock7mobile.com/downloads/IRDM_ISU_ATCommandReferenceMAN0009_Rev2.0_ATCOMM_Oct2012.pdf)
* [Arduino RockBLOCK library](http://arduiniana.org/libraries/iridiumsbd/)

## Overview
The RockBLOCK is an AT modem and previously we used a terminal session to send
AT commands directly, which is not a great user experience.

We want to develop a simple UI that talks to the modem and continually checks
for incoming messages, then triggers message reception, reads them from the
RockBLOCK, logs them to file and displays them on the screen. It should also
allow for composing an outgoing message, logging it to a file and writing it to
the RockBLOCK, then initiating transmission, monitoring transmission status,
retrying if required, and ultimately recording successful transmission.

My vague recollection is we used AT+SBDI to initiate message exchange, SBDWT to
write text messages, SBDRT to read a text message. SBDD to clear buffers, SBDS
to check status.

