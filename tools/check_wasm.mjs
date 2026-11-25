// Run the same bundled WASM inference engine used by the offline APK.
import fs from 'node:fs/promises';
import {performance} from 'node:perf_hooks';
import * as ort from '../web/vendor/ort.wasm.min.mjs';

const model=process.argv[2];
if(!model)throw new Error('Usage: node tools/check_wasm.mjs <net.onnx> [NCHW.f32] [output.f32] [size=640]');
const size=Number(process.argv[5]||640),count=(size/8)**2+(size/16)**2+(size/32)**2;
ort.env.wasm.numThreads=1;
ort.env.wasm.proxy=false;
ort.env.wasm.wasmPaths=new URL('../web/vendor/',import.meta.url).href;
const session=await ort.InferenceSession.create(await fs.readFile(model));
let data=new Float32Array(3*size*size);
if(process.argv[3]){
  const bytes=await fs.readFile(process.argv[3]);
  data=new Float32Array(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength));
  if(data.length!==3*size*size)throw new Error('Unexpected RGB float32 NCHW size');
}
const tensor=new ort.Tensor('float32',data,[1,3,size,size]);
let result;
try{
  const start=performance.now();
  result=await session.run({[session.inputNames[0]]:tensor});
  const output=result[session.outputNames[0]];
  if(output.dims.join(',')!==`1,5,${count}`)throw new Error('Unexpected one-class YOLOv8 output');
  if(!output.data.every(Number.isFinite))throw new Error('Non-finite model output');
  if(process.argv[4])await fs.writeFile(process.argv[4],Buffer.from(output.data.buffer,output.data.byteOffset,output.data.byteLength));
  console.log(JSON.stringify({engine:'Bundled ONNX Runtime Web WASM',dims:output.dims,inference_ms:Math.round(performance.now()-start),finite:true}));
}finally{
  tensor.dispose();
  if(result)for(const output of Object.values(result))output.dispose();
  await session.release();
}
