// Pure YOLOv8 decoding shared by browser inference and the software checks.
export function iou(a,b){const w=Math.max(0,Math.min(a[2],b[2])-Math.max(a[0],b[0])),h=Math.max(0,Math.min(a[3],b[3])-Math.max(a[1],b[1]));const intersection=w*h;return intersection/Math.max(1e-9,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection)}
export function decodeYolo(data,dims,{width,height,size=320,threshold=.4,names=['그물']}={}){
  if(dims.length!==3||dims[0]!==1)throw new Error('YOLOv8 출력 [1, 5, N] 형식이 필요합니다.');
  const channelsFirst=dims[1]<dims[2],attributes=channelsFirst?dims[1]:dims[2],count=channelsFirst?dims[2]:dims[1];
  if(attributes!==4+names.length)throw new Error('그물 한 종류를 학습한 YOLOv8 모델이 필요합니다.');
  const get=(row,col)=>channelsFirst?data[col*count+row]:data[row*attributes+col];
  const scale=Math.min(size/width,size/height),nw=Math.round(width*scale),nh=Math.round(height*scale),left=Math.floor((size-nw)/2),top=Math.floor((size-nh)/2),candidates=[];
  for(let i=0;i<count;i++){
    let score=-Infinity,cls=0;for(let c=4;c<attributes;c++){const s=get(i,c);if(s>score){score=s;cls=c-4}}
    if(!Number.isFinite(score)||score<threshold)continue;
    const cx=get(i,0),cy=get(i,1),w=get(i,2),h=get(i,3),box=[Math.max(0,(cx-w/2-left)/scale),Math.max(0,(cy-h/2-top)/scale),Math.min(width,(cx+w/2-left)/scale),Math.min(height,(cy+h/2-top)/scale)];
    if(box.every(Number.isFinite)&&box[2]>box[0]&&box[3]>box[1])candidates.push({box,score,cls,name:names[cls]});
  }
  candidates.sort((a,b)=>b.score-a.score);const kept=[];
  for(const c of candidates){if(!kept.some(k=>k.cls===c.cls&&iou(k.box,c.box)>.45))kept.push(c);if(kept.length>=40)break}return kept;
}
export function containRect(width,height,viewWidth,viewHeight){const scale=Math.min(viewWidth/width,viewHeight/height);return {scale,left:(viewWidth-width*scale)/2,top:(viewHeight-height*scale)/2}}
export class Detector{
  static async create(bytes){const ort=await import('./vendor/ort.wasm.min.mjs');ort.env.wasm.numThreads=1;ort.env.wasm.proxy=false;ort.env.wasm.wasmPaths=new URL('./vendor/',import.meta.url).href;const session=await ort.InferenceSession.create(bytes,{executionProviders:['wasm']});return new Detector(ort,session)}
  constructor(ort,session){this.ort=ort;this.session=session;this.canvas=document.createElement('canvas');this.canvas.width=this.canvas.height=320;this.ctx=this.canvas.getContext('2d',{willReadFrequently:true})}
  async predict(source,width,height,threshold){const size=320,scale=Math.min(size/width,size/height),nw=Math.round(width*scale),nh=Math.round(height*scale),left=Math.floor((size-nw)/2),top=Math.floor((size-nh)/2),ctx=this.ctx;ctx.fillStyle='rgb(114,114,114)';ctx.fillRect(0,0,size,size);ctx.drawImage(source,left,top,nw,nh);const pixels=ctx.getImageData(0,0,size,size).data,input=new Float32Array(3*size*size),plane=size*size;for(let i=0;i<plane;i++){input[i]=pixels[i*4]/255;input[plane+i]=pixels[i*4+1]/255;input[plane*2+i]=pixels[i*4+2]/255}const tensor=new this.ort.Tensor('float32',input,[1,3,size,size]);let outputs;try{outputs=await this.session.run({[this.session.inputNames[0]]:tensor});const output=outputs[this.session.outputNames[0]];return decodeYolo(output.data,output.dims,{width,height,threshold})}finally{tensor.dispose();if(outputs)Object.values(outputs).forEach(x=>x.dispose())}}
  async close(){await this.session.release()}
}
