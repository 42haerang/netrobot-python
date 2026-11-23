"""Meaningful software checks without sending power to real motors."""
import io
import json
from pathlib import Path
import sys
import threading
import time
import unittest
import zipfile

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'pc'),str(ROOT/'phone')]
from motors import Motors,mix
from server import create_app


class FakeCamera:
    def __init__(self):
        self.lock=threading.Lock()
        self.jpeg=cv2.imencode('.jpg',np.zeros((120,160,3),np.uint8))[1].tobytes()
        self.timestamp=time.monotonic()
        self.sequence=1
        self.error=''


class Checks(unittest.TestCase):
    def test_mixing_and_watchdog(self):
        self.assertEqual(mix('left',.3),[-.3,-.3,.3,.3])
        self.assertEqual(mix('backward',.3),[-.3]*4)
        with self.assertRaises(ValueError): mix('up',.3)
        with self.assertRaises(ValueError): mix('left',float('nan'))
        motors=Motors({'simulate':True})
        try:
            self.assertEqual(motors.drive('forward',.3)['motors'],[.3]*4)
            time.sleep(.42)
            self.assertEqual(motors.state()['motors'],[0.]*4)
        finally:
            motors.close()

    def test_api_auth_frame_and_controls(self):
        settings={'camera':0,'port':8765,'control_token':'test-only-token','pairing_code':'123456','controller':{'simulate':True}}
        camera=FakeCamera()
        motors=Motors({'simulate':True})
        app=create_app(settings,camera,motors)
        client=app.test_client()
        headers={'X-Control-Token':settings['control_token']}
        try:
            self.assertEqual(client.get('/frame.jpg').status_code,401)
            self.assertEqual(client.get('/frame.jpg',headers=headers).status_code,200)
            self.assertEqual(client.post('/control',json={'direction':'left','speed':.3},headers=headers).json['motors'],[-.3,-.3,.3,.3])
            self.assertEqual(client.post('/control',json={'direction':'unknown','speed':.3},headers=headers).status_code,400)
            camera.timestamp=0
            self.assertEqual(client.post('/control',json={'direction':'forward','speed':.3},headers=headers).status_code,409)
            self.assertEqual(motors.state()['motors'],[0.]*4)
            self.assertEqual(client.get('/phone.zip?code=bad').status_code,401)
            response=client.get('/phone.zip?code='+settings['pairing_code'])
            self.assertEqual(response.status_code,200)
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                self.assertIn('phone/main.py',archive.namelist())
                self.assertEqual(json.loads(archive.read('phone/config.json'))['token'],settings['control_token'])
        finally:
            motors.close()

    def test_mobile_onnx_if_present(self):
        if not (ROOT/'phone/models/net.onnx').exists():
            self.skipTest('model export still running')
        from detector import Detector
        detector=Detector(ROOT/'phone/models')
        rows=detector.predict(np.zeros((240,320,3),np.uint8))
        self.assertIsInstance(rows,list)


if __name__=='__main__':
    unittest.main(verbosity=2)
