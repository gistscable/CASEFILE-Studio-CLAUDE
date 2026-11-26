class Rec extends AudioWorkletProcessor {
  constructor() { super(); this.on = [[], []]; this.quiet = [1e9, 1e9]; this.port.onmessage = () => this.port.postMessage(this.on); }
  process(inputs) {
    const inp = inputs[0];
    for (let c = 0; c < 2; c++) {
      const x = inp[c]; if (!x) continue;
      for (let i = 0; i < x.length; i++) {
        if (Math.abs(x[i]) > 0.12) { if (this.quiet[c] > 0.15 * sampleRate) this.on[c].push(currentTime + i / sampleRate); this.quiet[c] = 0; }
        else this.quiet[c]++;
      }
    }
    return true;
  }
}
registerProcessor('rec', Rec);
