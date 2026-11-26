# v0.4.59 QA scratch script kept for reproducibility (run from casefile-studio/ with PATH=$PWD/.venv/bin:$PATH, PYTHONPATH=$PWD).
N=n5.mp3
t(){ s=$(date +%s.%N); "$@"; e=$(date +%s.%N); python3 -c "print(round($e-$s,2))"; }
G=""; L=""; for i in $(seq 0 29); do L="$L[s$i]"; done
G="[0:a]asetpts=N/SR/TB,asplit=30$L"
J=""; for i in $(seq 0 29); do a=$((i*10)); G="$G;[s$i]atrim=start=$a:end=$((a+10)),asetpts=PTS-STARTPTS,apad,atrim=duration=10[v$i]"; J="$J[v$i]"; done
echo -n "asplit30 no loudnorm: "; t ffmpeg -v error -nostdin -i $N -filter_complex "$G;${J}concat=n=30:v=0:a=1,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[o]" -map "[o]" -f null -
echo -n "asplit30 + loudnorm: "; t ffmpeg -v error -nostdin -i $N -filter_complex "$G;${J}concat=n=30:v=0:a=1,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,loudnorm=I=-16:TP=-1.5:LRA=11[o]" -map "[o]" -f null -
echo -n "continuous + loudnorm: "; t ffmpeg -v error -nostdin -i $N -filter_complex "[0:a]asetpts=N/SR/TB,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,loudnorm=I=-16:TP=-1.5:LRA=11[o]" -map "[o]" -f null -
echo -n "decode only: "; t ffmpeg -v error -nostdin -i $N -f null -
