import {Detector,containRect} from './vision.js';
import {joystickVector,directionLabel} from './control.js';
import {RobotHologram} from './robot.js';
import {readModel,saveModel} from './model_store.js';
const $=id=>document.getElementById(id);
const state={source:'none',remoteGeneration:0,frameAt:0,lastSequence:null,width:0,height:0,frames:0,fpsAt:performance.now(),vector:{x:0,y:0},grip:'stop',paused:false,bridge:null,remoteReady:false,detector:null,detectEnabled:localStorage.getItem('netrobot-detection')!=='off',detecting:false,detectError:false,detections:[],inferenceMs:0,threshold:.4,joystickPointer:null,gripperPointer:null,keys:new Set(),previewTimer:0};
let toastTimer,controlsBusy=false,modelLoading=false;
const robot=new RobotHologram();
const nativeApp=location.hostname==='appassets.androidplatform.net';
if(nativeApp)document.body.classList.add('native-app');
async function sendControls(){}
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,4500)}
function cameraState(text,live=false){$('connectionState').lastElementChild.textContent=text;$('connectionState').title=text;$('connectionState').classList.toggle('live',live)}
function renderControls(){const {x,y}=state.vector;const power=state.paused?0:Math.round(Math.min(1,Math.hypot(x,y))*50);$('powerValue').textContent=power;$('directionState').textContent=directionLabel(state.vector);$('gripperState').textContent=state.grip==='open'?'열림 동작':state.grip==='close'?'닫힘 동작':'대기';$('gripperOpen').classList.toggle('active',state.grip==='open');$('gripperClose').classList.toggle('active',state.grip==='close');$('joystick').setAttribute('aria-valuenow',String(power));$('joystick').setAttribute('aria-valuetext',directionLabel(state.vector));}
function resetDrive(){state.vector={x:0,y:0};state.keys.clear();$('joystickKnob').style.transform='translate(0,0)';$('joystick').classList.remove('dragging');state.joystickPointer=null;renderControls()}
function resetGrip(){state.grip='stop';state.gripperPointer=null;renderControls()}
function allStop(){resetDrive();resetGrip();void sendControls(true)}
function releaseCamera(){state.remoteGeneration++;state.source='none';state.frameAt=0;state.remoteReady=false;state.detections=[];state.lastSequence=null;for(const id of ['remoteFrame','demoFrame'])$(id).hidden=true;allStop()}
function setSource(source){state.source=source;$('welcome').hidden=true;$('previewBadge').hidden=source!=='demo';$('sourceLabel').textContent=source==='native'?'DRONE WIFI · OFFLINE':source==='camera'?'DEVICE CAMERA':'CONTROL PRACTICE';$('cameraError').textContent='';$('connectionError').textContent='';$('motorMode').textContent=state.bridge&&state.remoteReady?'연결 확인 중':'모의 조종';updateVisionState()}
function updateVisionState(){if(!state.detectEnabled){$('visionState').textContent='그물 감지 꺼짐';$('modelState').textContent='설정에서 감지를 켤 수 있습니다';$('netCount').textContent='—';return}if(state.source==='demo'){$('visionState').textContent='조종 연습';$('modelState').textContent='가상 그물 · 사각형 표시 예시';$('netCount').textContent='예시';return}if(state.detector&&!state.detectError){$('visionState').textContent=state.source==='none'?'그물 모델 준비됨':state.detections.length?`그물 ${state.detections.length}개 감지`:'그물 탐색 중';$('modelState').textContent=`이 기기에서 YOLO 실행${state.inferenceMs?' · '+Math.round(state.inferenceMs)+'ms':''}`;$('netCount').textContent=state.detections.length}else{$('visionState').textContent=state.detectError?'모델 형식 확인 필요':'그물 감지 준비';$('modelState').textContent=state.detectError?'설정에서 1종류 그물 모델을 선택하세요':'그물 전용 모델 준비 중 · 모델 불러오기 가능';$('netCount').textContent='—'}}

function startDemo(){if(nativeApp)void nativeRequest('/disconnect');releaseCamera();state.bridge=null;state.paused=false;$('pausedBanner').hidden=true;$('demoFrame').hidden=false;setSource('demo');cameraState('연습 모드',true);$('motorMode').textContent='모의 조종';$('settingsDialog').close();toast('조종 연습입니다. 가상 화면이며 실제 카메라 감지가 아닙니다.');}
function openSettings(){allStop();$('connectionError').textContent='';if(!document.querySelector('dialog[open]'))$('settingsDialog').showModal()}
function canControl(){if(state.paused)return false;return !state.bridge||state.source==='demo'||(state.source==='native'&&state.remoteReady&&performance.now()-state.frameAt<1000)}
const joystick=$('joystick');
function updateJoystick(event){const rect=joystick.getBoundingClientRect(),radius=rect.width*.34;state.vector=joystickVector(event.clientX-rect.left-rect.width/2,event.clientY-rect.top-rect.height/2,radius);$('joystickKnob').style.transform=`translate(${state.vector.x*radius}px,${-state.vector.y*radius}px)`;renderControls()}
joystick.addEventListener('pointerdown',event=>{if(state.joystickPointer!==null)return;if(!canControl()){toast(state.paused?'조종 재개를 눌러주세요.':'카메라를 연결하거나 조종 연습을 시작하세요.');return}event.preventDefault();state.joystickPointer=event.pointerId;joystick.setPointerCapture(event.pointerId);joystick.classList.add('dragging');updateJoystick(event)});
joystick.addEventListener('pointermove',event=>{if(state.joystickPointer===event.pointerId)updateJoystick(event)});
for(const name of ['pointerup','pointercancel','lostpointercapture'])joystick.addEventListener(name,event=>{if(state.joystickPointer===event.pointerId){resetDrive();void sendControls(true)}});
for(const [id,action] of [['gripperOpen','open'],['gripperClose','close']]){const button=$(id);button.addEventListener('pointerdown',event=>{if(state.gripperPointer!==null)return;if(!canControl()){toast(state.paused?'조종 재개를 눌러주세요.':'먼저 카메라 연결 또는 조종 연습을 시작하세요.');return}event.preventDefault();state.gripperPointer=event.pointerId;button.setPointerCapture(event.pointerId);state.grip=action;renderControls();void sendControls(true)});for(const name of ['pointerup','pointercancel','lostpointercapture'])button.addEventListener(name,event=>{if(state.gripperPointer===event.pointerId){resetGrip();void sendControls(true)}});button.addEventListener('keydown',event=>{if([' ','Enter'].includes(event.key)&&canControl()){event.preventDefault();state.grip=action;renderControls()}});button.addEventListener('keyup',()=>{resetGrip();void sendControls(true)});button.addEventListener('blur',()=>{if(state.bridge&&!state.bridge.simulated)resetGrip()});button.addEventListener('click',()=>{if((!state.bridge||state.bridge.simulated)&&canControl()){state.grip=action;renderControls()}})}
const keyVectors={ArrowUp:[0,1],w:[0,1],ArrowDown:[0,-1],s:[0,-1],ArrowLeft:[-1,0],a:[-1,0],ArrowRight:[1,0],d:[1,0]};
function updateKeys(){let x=0,y=0;for(const key of state.keys){x+=keyVectors[key][0];y+=keyVectors[key][1]}const length=Math.max(1,Math.hypot(x,y));state.vector={x:x/length,y:y/length};const radius=joystick.clientWidth*.34;$('joystickKnob').style.transform=`translate(${state.vector.x*radius}px,${-state.vector.y*radius}px)`;renderControls()}
window.addEventListener('keydown',e=>{if(['INPUT','TEXTAREA'].includes(e.target.tagName)||$('settingsDialog').open)return;if(e.code==='Space'&&e.target===document.body){e.preventDefault();emergencyStop();return}const key=e.key.length===1?e.key.toLowerCase():e.key;if(keyVectors[key]&&canControl()){e.preventDefault();state.keys.add(key);updateKeys()}});
window.addEventListener('keyup',e=>{const key=e.key.length===1?e.key.toLowerCase():e.key;if(state.keys.delete(key)){updateKeys();void sendControls(true)}});
function emergencyStop(){state.paused=true;allStop();$('pausedBanner').hidden=false;toast('주행과 집게를 정지했습니다.');}
$('stopButton').onclick=emergencyStop;$('resumeButton').onclick=()=>{state.paused=false;$('pausedBanner').hidden=true;allStop()};
window.addEventListener('blur',allStop);window.addEventListener('pagehide',()=>{allStop();if(state.bridge)fetch(state.bridge.url+'/drive',{method:'POST',headers:{'X-Control-Token':state.bridge.token,'Content-Type':'application/json'},body:JSON.stringify({x:0,y:0,speed:0,gripper:'stop',session:state.bridge.session,sequence:++state.bridge.sequence}),keepalive:true}).catch(()=>{})});document.addEventListener('visibilitychange',()=>{if(document.hidden)allStop()});
$('cameraButton').onclick=()=>nativeApp?connectDrone():openSettings();$('settingsButton').onclick=openSettings;$('connectLaptop').onclick=openSettings;$('closeSettings').onclick=()=>$('settingsDialog').close();$('settingsDialog').addEventListener('close',allStop);$('droneWifiButton').onclick=()=>nativeApp?nativeRequest('/wifi'):toast('APK에서 Wi-Fi 설정을 열 수 있습니다.');$('startDemo').onclick=startDemo;$('demoButton').onclick=startDemo;$('connectionForm').onsubmit=connectDrone;
$('fullscreenButton').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await $('cockpit').requestFullscreen();if(screen.orientation?.lock)await screen.orientation.lock('landscape').catch(()=>{})}catch{toast('브라우저 메뉴에서 전체 화면을 선택하세요.')}};
$('detectionToggle').checked=state.detectEnabled;
$('detectionToggle').onchange=e=>{state.detectEnabled=e.target.checked;localStorage.setItem('netrobot-detection',state.detectEnabled?'on':'off');state.detections=[];updateVisionState()};
$('threshold').oninput=e=>{state.threshold=Number(e.target.value)/100;$('thresholdValue').value=e.target.value+'%'};
async function loadModel(bytes,name){if(modelLoading)return;modelLoading=true;$('modelState').textContent='YOLO 모델 준비 중…';try{const candidate=await Detector.create(bytes);try{const blank=document.createElement('canvas');blank.width=blank.height=320;await candidate.predict(blank,320,320,.4)}catch(e){await candidate.close();throw e}while(state.detecting)await new Promise(r=>setTimeout(r,30));const old=state.detector;state.detector=candidate;state.detectError=false;if(old)await old.close();updateVisionState();toast(`그물 모델 연결됨: ${name}`);return true}catch(error){toast('모델을 불러오지 못했습니다: '+error.message);$('connectionError').textContent=error.message;updateVisionState();return false}finally{modelLoading=false}}
$('modelFile').onchange=async e=>{const file=e.target.files[0];if(file){const bytes=await file.arrayBuffer();if(await loadModel(bytes,file.name))await saveModel(bytes,file.name).catch(()=>toast('모델은 연결됐지만 기기 저장 공간을 확인하세요.'))}};
let previousDetect=0;
async function infer(source,width,height){if(!state.detectEnabled||modelLoading||!state.detector||state.detecting||state.detectError||state.source==='demo'||performance.now()-previousDetect<100)return;state.detecting=true;previousDetect=performance.now();const generation=state.remoteGeneration;try{const start=performance.now(),result=await state.detector.predict(source,width,height,state.threshold);if(generation===state.remoteGeneration&&state.detectEnabled){state.detections=result;state.inferenceMs=performance.now()-start;updateVisionState()}}catch(error){state.detectError=true;state.detections=[];updateVisionState();toast('감지 오류: '+error.message)}finally{state.detecting=false}}
// A deliberately synthetic, labelled practice scene; never used as live detections.
function drawPractice(now){const canvas=$('demoFrame');if(canvas.width!==1280){canvas.width=1280;canvas.height=720}const ctx=canvas.getContext('2d'),gradient=ctx.createLinearGradient(0,0,0,720);gradient.addColorStop(0,'#485c61');gradient.addColorStop(1,'#202f39');ctx.fillStyle=gradient;ctx.fillRect(0,0,1280,720);ctx.strokeStyle='#ffffff05';ctx.lineWidth=1;for(let y=0;y<720;y+=28){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(1280,y+45);ctx.stroke()}const drift=Math.sin(now/2400)*5,box=[405+drift,190,875+drift,520];ctx.save();ctx.translate(640+drift,350);ctx.rotate(-.12);ctx.strokeStyle='#b4c3a366';ctx.lineWidth=3;for(let i=-270;i<=270;i+=25){ctx.beginPath();for(let j=-170;j<=170;j+=10){const x=i+j*.5+Math.sin(j/70+now/5000)*7;if(j===-170)ctx.moveTo(x,j);else ctx.lineTo(x,j)}ctx.stroke();ctx.beginPath();for(let j=-170;j<=170;j+=10){const x=i-j*.5+Math.sin(j/65+now/5000)*7;if(j===-170)ctx.moveTo(x,j);else ctx.lineTo(x,j)}ctx.stroke()}ctx.restore();state.width=1280;state.height=720;state.frameAt=now;state.frames++;state.detections=[{box,score:null,name:'그물 표시 예시'}];}
function drawBoxes(now){const canvas=$('boxes'),w=innerWidth,h=innerHeight,dpr=Math.min(devicePixelRatio||1,2);if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr)}const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);if(!state.detectEnabled||!state.width||now-state.frameAt>1200)return;const fit=containRect(state.width,state.height,w,h);ctx.font='600 14px system-ui';for(const r of state.detections){const [x1,y1,x2,y2]=r.box,x=fit.left+x1*fit.scale,y=fit.top+y1*fit.scale,bw=(x2-x1)*fit.scale,bh=(y2-y1)*fit.scale;ctx.strokeStyle='#a5f4c6';ctx.lineWidth=1.4;ctx.strokeRect(x,y,bw,bh);ctx.lineWidth=3;const c=14;for(const [cx,cy,sx,sy] of [[x,y,1,1],[x+bw,y,-1,1],[x,y+bh,1,-1],[x+bw,y+bh,-1,-1]]){ctx.beginPath();ctx.moveTo(cx+sx*c,cy);ctx.lineTo(cx,cy);ctx.lineTo(cx,cy+sy*c);ctx.stroke()}const text=r.score===null?r.name:`그물 ${Math.round(r.score*100)}%`;const tw=ctx.measureText(text).width+20,ly=Math.max(4,y-31);ctx.fillStyle='#a5f4c6';ctx.beginPath();ctx.roundRect(x,ly,tw,26,4);ctx.fill();ctx.fillStyle='#11251d';ctx.fillText(text,x+10,ly+18)}}
function tick(now){robot.update(now,state.vector,state.grip,state.paused);if((!state.bridge||state.bridge.simulated)&&state.gripperPointer===null&&((state.grip==='open'&&robot.openness>=1)||(state.grip==='close'&&robot.openness<=0)))resetGrip();if(state.source==='native'&&state.frameAt&&now-state.frameAt<1000&&!document.hidden){void infer($('remoteFrame'),state.width,state.height)}else if(state.source==='demo'){drawPractice(now)}if(now-state.fpsAt>1000){$('frameRate').textContent=state.source==='none'?'— FPS':Math.round(state.frames*1000/(now-state.fpsAt))+' FPS';$('frameSize').textContent=state.width?`${state.width} × ${state.height}`:'— × —';state.fpsAt=now;state.frames=0}drawBoxes(now);requestAnimationFrame(tick)}

async function nativeRequest(path,query={}){
  const url=new URL('/native'+path,location.origin);
  for(const [key,value] of Object.entries(query))url.searchParams.set(key,value);
  const response=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(2500)});
  if(!response.ok){let message='드론 응답 대기';try{message=(await response.json()).error||message}catch{}throw new Error(message)}
  return response;
}
async function connectDrone(event){
  event?.preventDefault();
  if(!nativeApp){$('connectionError').textContent='드론 UDP 영상은 APK에서 직접 받습니다. 위 Android APK 다운로드 버튼을 사용하세요.';toast('APK를 설치하고 드론 Wi-Fi에 연결하세요.');return}
  const host=$('droneAddress').value.trim(),mode=$('jpegMode').value;
  $('pairButton').disabled=true;
  try{
    releaseCamera();
    await nativeRequest('/connect',{host,mode});
    localStorage.setItem('netrobot-drone',host);localStorage.setItem('netrobot-jpeg-mode',mode);
    $('remoteFrame').hidden=false;setSource('native');cameraState('드론 영상 응답 대기');$('settingsDialog').close();
    const generation=state.remoteGeneration;void droneFrames(generation);
  }catch(error){$('connectionError').textContent=error.message;toast(error.message)}finally{$('pairButton').disabled=false}
}
async function droneFrames(generation){
  while(state.source==='native'&&generation===state.remoteGeneration){
    try{
      const status=await (await nativeRequest('/status')).json();
      if(!status.ready){cameraState(status.error||'FLOW Wi-Fi 연결을 확인하세요.');await new Promise(r=>setTimeout(r,350));continue}
      if(status.sequence===state.lastSequence){await new Promise(r=>setTimeout(r,40));continue}
      const response=await nativeRequest('/frame.jpg'),image=await createImageBitmap(await response.blob());
      if(generation!==state.remoteGeneration){image.close();break}
      const canvas=$('remoteFrame');canvas.width=image.width;canvas.height=image.height;canvas.getContext('2d').drawImage(image,0,0);image.close();
      state.width=canvas.width;state.height=canvas.height;state.frameAt=performance.now();state.lastSequence=status.sequence;state.frames++;
      cameraState('드론 영상 연결됨',true);$('motorMode').textContent='모의 조종';
    }catch(error){if(generation===state.remoteGeneration)cameraState('영상 수신 대기 · FLOW Wi-Fi 확인')}
    await new Promise(r=>setTimeout(r,70));
  }
}
$('droneAddress').value=localStorage.getItem('netrobot-drone')||'192.168.169.1';
$('jpegMode').value=localStorage.getItem('netrobot-jpeg-mode')||'zigzag';
window.netrobotPause=()=>{releaseCamera();};
window.netrobotResume=()=>{if(nativeApp&&!$('settingsDialog').open&&state.source!=='demo')void connectDrone();};
if(nativeApp)void connectDrone();

async function restoreModel(){
 try{const saved=await readModel();if(saved&&await loadModel(saved.bytes,saved.name))return}catch{}
 try{const response=await fetch(new URL('./models/model.json',import.meta.url));if(!response.ok)return;const info=await response.json();if(info.available&&info.trained_on_net){const model=await fetch(new URL('./models/'+info.file,import.meta.url));if(!model.ok)throw new Error('모델 파일이 없습니다.');await loadModel(await model.arrayBuffer(),'기본 그물 모델')}}catch(error){toast('기본 모델 확인: '+error.message)}
}
void restoreModel();
renderControls();requestAnimationFrame(tick);
