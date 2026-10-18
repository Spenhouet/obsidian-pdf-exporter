#!/bin/bash
# loop.sh <mode> <n> <worker>: rerun the latin-only blame job of the scripts tests
B=$PWD/bt/scripts0/latin-only; D=$PWD/ci_debug/out; mode=$1; n=$2; w=$3
mkdir -p $D/w$w; sed "s#<cachedir>.*</cachedir>#<cachedir>$D/w$w/cache</cachedir>#" $B/fonts.conf > $D/w$w/fonts.conf
sed "s#$B/blame-default#$D/w$w/out#g" $B/blame-default.job.json > $D/w$w/job.json
crashes=0
for i in $(seq $n); do
  rm -rf $D/w$w/cache
  ( cd $B && FONTCONFIG_FILE=$D/w$w/fonts.conf PYTHONIOENCODING=utf-8 PYTHONFAULTHANDLER=1 RUNNER=$OLDPWD/tests/scripts_runner.py \
    $OLDPWD/.venv/bin/python $OLDPWD/ci_debug/run_job.py $D/w$w/job.json $mode > $D/w$w/last.out 2> $D/w$w/last.err )
  rc=$?
  if [ $rc -ne 0 ]; then crashes=$((crashes+1)); echo "CRASH mode=$mode w=$w i=$i rc=$rc"; tail -60 $D/w$w/last.err; fi
done
echo "done mode=$mode w=$w crashes=$crashes"
