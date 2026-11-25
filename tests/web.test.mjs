import test from 'node:test';
import assert from 'node:assert/strict';
import {joystickVector,differential} from '../web/control.js';
import {decodeYolo,containRect} from '../web/vision.js';

test('640 input boxes map back through letterbox to the camera frame',()=>{
  const n=10,data=new Float32Array(5*n);
  for(const [channel,value] of [320,320,200,160,.9].entries())data[channel*n]=value;
  const boxes=decodeYolo(data,[1,5,n],{width:1280,height:720,size:640,threshold:.4});
  assert.equal(boxes.length,1);
  assert.deepEqual(boxes[0].box,[440,200,840,520]);
});
test('joystick dead zone, edge clamping and opposing wheel rotation',()=>{
  assert.deepEqual(joystickVector(1,1,60),{x:0,y:0});
  assert.deepEqual(joystickVector(0,-100,60),{x:0,y:1});
  assert.deepEqual(differential(-1,0,.5),[-.5,-.5,.5,.5]);
  assert.deepEqual(differential(1,1,.5),[.5,.5,0,0]);
  assert.throws(()=>differential(NaN,0,.5));
});
test('YOLO letterbox projection, threshold and NMS suppress only overlapping boxes',()=>{
  const n=10,data=new Float32Array(5*n);
  for(const [i,x,y,w,h,score] of [[0,160,160,100,80,.9],[1,161,160,100,80,.8],[2,40,120,20,20,.7]]){
    for(const [j,value] of [x,y,w,h,score].entries())data[j*n+i]=value;
  }
  const result=decodeYolo(data,[1,5,n],{width:640,height:480,threshold:.4});
  assert.equal(result.length,2);assert.deepEqual(result[0].box,[220,160,420,320]);
  const fit=containRect(640,480,1000,500);assert.ok(Math.abs(fit.scale-500/480)<1e-12);assert.ok(Math.abs(fit.left-166.6666666667)<1e-8);assert.ok(Math.abs(fit.top)<1e-10);
  assert.throws(()=>decodeYolo(new Float32Array(840),[1,84,10],{width:640,height:480}));
});
