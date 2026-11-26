# v0.4.59 QA scratch script kept for reproducibility (run from casefile-studio/ with PATH=$PWD/.venv/bin:$PATH, PYTHONPATH=$PWD).
import json, subprocess, numpy as np
c = json.load(open('/tmp/cap.json'))
fc = c[c.index('-filter_complex') + 1].split(';')
ins = []
k = 0
args = c[c.index('-y') + 1: c.index('-map')]
args = args[args.index('-filter_complex_threads') + 2:]
# drop the picture input (index 0) and renumber: replace with a dummy anullsrc input 0
args = ['-f', 'lavfi', '-i', 'anullsrc=d=1'] + args[2:]
nar = np.frombuffer(subprocess.run(['ffmpeg', '-v', 'error'] + args + ['-filter_complex', ';'.join(fc[:6]) , '-map', '[voice]', '-f', 'f32le', '-ac', '1', '-ar', '48000', '-'], capture_output=True).stdout, np.float32)
def run(name, graph):
    r = subprocess.run(['ffmpeg', '-v', 'warning'] + args + ['-filter_complex', ';'.join(graph), '-map', '[aout]', '-f', 'f32le', '-ac', '1', '-ar', '48000', '-'], capture_output=True)
    a = np.frombuffer(r.stdout, np.float32)
    n = min(len(a), len(nar)); m = a[:n] - nar[:n]
    db = lambda x: round(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12), 1)
    print(f"{name:45s} len {len(a)/48000:.2f}  music dB at 5s {db(m[5*48000:6*48000])}  15s {db(m[15*48000:16*48000])}  35s {db(m[35*48000:36*48000])}", r.stderr.decode()[-200:].strip())
base = fc[:13]  # up to [voice]asplit
tail = fc[-1].replace('alimiter=limit=0.95:attack=5:release=50:level=disabled:latency=1', 'anull')
run("current (apad main)", fc[:16] + [tail])
run("old (no apad)", fc[:13] + ['[bed][side]sidechaincompress=threshold=0.03:ratio=8:attack=30:release=800[ducked]', tail])
run("apad main, no output apad", fc[:13] + ['[bed]apad[x]', '[x][side]sidechaincompress=threshold=0.03:ratio=8:attack=30:release=800,atrim=end_sample=1920000[ducked]', tail])
run("no compressor", fc[:13] + ['[side]anullsink', '[bed]anull[ducked]', tail])
run("apad=whole_len only", fc[:13] + ['[bed]apad=whole_len=2000000[x]', '[x][side]sidechaincompress=threshold=0.03:ratio=8:attack=30:release=800,atrim=end_sample=1920000[ducked]', tail])
print("----")
C = 'sidechaincompress=threshold=0.03:ratio=8:attack=30:release=800'
mix = lambda dur, extra='': f'[main][ducked]amix=inputs=2:duration={dur}:normalize=0{extra},anull[aout]'
run("no comp, amix longest+atrim", fc[:13] + ['[side]anullsink', '[bed]anull[ducked]', mix('longest', ',atrim=end_sample=1920000')])
run("old comp, amix longest+atrim", fc[:13] + [f'[bed][side]{C}[ducked]', mix('longest', ',atrim=end_sample=1920000')])
run("old comp + apad after comp, amix first", fc[:13] + [f'[bed][side]{C},apad[ducked]', mix('first')])
run("voice apad+atrim, old comp, amix first", fc[:5] + [fc[5].replace('[voice]', ',apad,atrim=end_sample=1920000[voice]')] + fc[6:13] + [f'[bed][side]{C}[ducked]', mix('first')])
