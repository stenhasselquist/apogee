#!/bin/csh -f
# compute intensity spectrum for the Sun, at 2 different angles


date
set mpath=models

foreach MODEL (s5000_g+2.0_m1.0_t02_st_z+0.00_a+0.00_c+0.00_n+0.00_o+0.00_r+0.00_s+0.00.mod)

set lam_min    = '6700'
set lam_max    = '6720'

set deltalam   = '0.01'
set METALLIC   = '     0.000'
set TURBVEL    = '2.0'

#
# ABUNDANCES FROM THE MODEL ARE NOT USED !!!

../exec-v19.2/babsma_lu << EOF
'LAMBDA_MIN:'  '${lam_min}'
'LAMBDA_MAX:'  '${lam_max}'
'LAMBDA_STEP:' '${deltalam}'
'MODELINPUT:' '$mpath/${MODEL}'
'MARCS-FILE:' '.true.'
'MODELOPAC:' 'contopac/${MODEL}opac'
'METALLICITY:'    '${METALLIC}'
'ALPHA/Fe   :'    '0.00'
'HELIUM     :'    '0.00'
'R-PROCESS  :'    '0.00'
'S-PROCESS  :'    '0.00'
'INDIVIDUAL ABUNDANCES:'   '0'
'XIFIX:' 'T'
$TURBVEL
EOF

########################################################################

set SUFFIX     = _${lam_min}-${lam_max}_xit${TURBVEL}.intensity
set result     = ${MODEL}${SUFFIX}

../exec-v19.2/bsyn_lu <<EOF
'LAMBDA_MIN:'     '${lam_min}'
'LAMBDA_MAX:'     '${lam_max}'
'LAMBDA_STEP:'    '${deltalam}'
'INTENSITY/FLUX:' 'Intensity'
'COS(THETA)    :' '1.0'
'ABFIND        :' '.false.'
'MODELOPAC:' 'contopac/${MODEL}opac'
'RESULTFILE :' 'syntspec/${result}'
'METALLICITY:'    '${METALLIC}'
'ALPHA/Fe   :'    '0.00'
'HELIUM     :'    '0.00'
'R-PROCESS  :'    '0.00'
'S-PROCESS  :'    '0.00'
'INDIVIDUAL ABUNDANCES:'   '1'
3  1.05
'ISOTOPES : ' '2'
3.006  0.075
3.007  0.925
'NFILES   :' '2'
DATA/Hlinedata
linelists/vald-6700-6720.list
'SPHERICAL:'  'T'
  30
  300.00
  15
  1.30
EOF

########################################################################
date
end
