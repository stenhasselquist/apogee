#!/bin/csh

set configfile = $1.cfg
shift

# set defaults for non-required params
set commiss = 0
set nored = 0
set npar = 0
set caldir = 0
set renorm = 0
set maxwind = 0

# set parameters from configuration file
set cmd = `awk '{printf("set %s = %s\n",$1,$2)}' $configfile`
echo $cmd
$cmd

# setup idlwrap version based on config file value
echo aspcap_vers : $aspcap_vers
if ( $?UUFSCELL ) then
  set uva = 0
  alias idl $IDL_DIR/bin/idl
endif


# make the individual .par files for each requested field
set fields = ($*)
echo $fields
idl << endidl

  fields='$*'
  field=strsplit(fields,' ',/ext)
  help,fields,field
  print,fields
  print,field
  print,'$apred_vers'
  print,'$apstar_vers'
  print,'$aspcap_vers'
  print,'$results_vers'
  aspcap_mkplan,field,apred_vers='$apred_vers',apstar_vers='$apstar_vers',aspcap_vers='$aspcap_vers',aspcap_config='$aspcap_config',ncpus='$ncpus',queue='$queue',noplot='$noplot',noelem='$noelem',nstars='$nstars',commiss=$commiss,nored=$nored,visits='$visits',caldir='$caldir',npar='$npar',renorm='$renorm',maxwind='$maxwind'
  aspcap_mkplan,field,apred_vers='$apred_vers',apstar_vers='$apstar_vers',aspcap_vers='$aspcap_vers',aspcap_config='$aspcap_config',ncpus='$ncpus',queue='$queue',noplot='$noplot',noelem='$noelem',nstars='$nstars',commiss=$commiss,nored=$nored,visits='$visits',caldir='$caldir',npar='$npar',renorm='$renorm',maxwind='$maxwind',/single
endidl


cd $APOGEE_ASPCAP/$apred_vers/$aspcap_vers
mkslurm "aspcap apo*/plan/aspcapStar*.par lco*/plan/aspcapStar*.par" --maxrun=2 --idlthreads=16 --queryport=1051

echo "\n\nREMEMBER to modify the aspcapStar*.par files if non-default options,"
echo "  e.g., noplot, noelem, fits, are desired"
