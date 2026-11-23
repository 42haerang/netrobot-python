import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pc'))
from motors import Motors,mix_vector
from server import create_app
from test_system import FakeCamera


class WebControls(unittest.TestCase):
    def test_analog_direction_and_finite_inputs(self):
        self.assertEqual(mix_vector(1,0,.4),[.4,.4,-.4,-.4])
        self.assertEqual(mix_vector(-1,0,.4),[-.4,-.4,.4,.4])
        self.assertEqual(mix_vector(0,1,.4),[.4]*4)
        self.assertEqual(mix_vector(0,-1,.4),[-.4]*4)
        for x in [float('nan'),float('inf'),1.1]:
            with self.assertRaises(ValueError): mix_vector(x,0,.4)

    def test_gripper_limits_watchdog_and_release(self):
        motors=Motors({'simulate':True,'gripper_max_seconds':.15})
        try:
            self.assertGreater(motors.grip('open')['gripper'],0)
            time.sleep(.21)
            self.assertEqual(motors.state()['gripper'],0)
            self.assertTrue(motors.state()['gripper_limit_reached'])
            self.assertEqual(motors.grip('open')['gripper'],0)
            motors.grip('stop')
            self.assertLess(motors.grip('close')['gripper'],0)
            motors.grip('stop')
            self.assertEqual(motors.state()['gripper'],0)
        finally:
            motors.close()

    def test_pairing_stale_commands_video_loss_and_origins(self):
        settings={'control_token':'test-only-secret','pairing_code':'123456','controller':{'simulate':True}}
        motors=Motors(settings['controller'])
        camera=FakeCamera()
        client=create_app(settings,camera,motors).test_client()
        try:
            for url in ('/','/app.js'):
                with client.get(url) as response:
                    self.assertEqual(response.status_code,200)
            with client.get('/vendor/ort.wasm.min.mjs') as response:
                self.assertEqual(response.mimetype,'text/javascript')
            self.assertEqual(client.post('/pair',json={'code':'000000'}).status_code,401)
            self.assertEqual(client.post('/pair',json={'code':'123456'},headers={'Origin':'https://untrusted.invalid'}).status_code,403)
            paired=client.post('/pair',json={'code':'123456'}).json
            headers={'X-Control-Token':paired['token']}
            command={'session':paired['session'],'sequence':1,'x':0,'y':1,'speed':.3,'gripper':'close'}
            response=client.post('/drive',json=command,headers=headers)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['motors'],[.3]*4)
            self.assertLess(response.json['gripper'],0)
            response=client.post('/drive',json={**command,'sequence':2,'x':0,'y':0,'gripper':'stop'},headers=headers)
            self.assertEqual(response.json['motors'],[0.]*4)
            response=client.post('/drive',json=command,headers=headers)
            self.assertTrue(response.json['ignored_stale_command'])
            self.assertEqual(response.json['motors'],[0.]*4)
            camera.timestamp=0
            self.assertEqual(client.post('/drive',json={**command,'sequence':3},headers=headers).status_code,409)
            self.assertEqual(motors.state()['gripper'],0)
            self.assertEqual(client.get('/net-model.onnx',headers=headers).status_code,404)
        finally:
            motors.close()
