import sys
import os
sys.path.append(os.getcwd())
from ur5 import UR5

import time
import numpy.random as random
import numpy as np
import math
import PIL.Image as Image
import array
import h5py
import cv2 as cv

try:
    import vrep
except:
    print ('--------------------------------------------------------------')
    print ('"vrep.py" could not be imported. This means very probably that')
    print ('either "vrep.py" or the remoteApi library could not be found.')
    print ('Make sure both are in the same folder as this file,')
    print ('or appropriately adjust the file "vrep.py"')
    print ('--------------------------------------------------------------')
    print ('')

# Make sure to have the server side running in V-REP: 
# in a child script of a V-REP scene, add following command
# to be executed just once, at simulation start:
#
# simRemoteApi.start(19999)
#
# then start simulation, and run this program.


class Camera():

    def __init__(self, clientID):
        """
            Initialize the Camera in simulation
        """
        # self.RAD2EDG = 180 / math.pi
        self.Save_IMG = True
        self.Save_PATH_COLOR = r'./color/'
        self.Save_PATH_DEPTH = r'./depth/'
        self.Dis_NEAR = 0.01
        self.Dis_FAR = 10
        self.INT16 = 65535
        self.Img_WIDTH = 512
        self.Img_HEIGHT = 424
        self.Camera_NAME = r'kinect'
        self.Camera_RGB_NAME = r'kinect_rgb'
        self.Camera_DEPTH_NAME = r'kinect_depth'
        self.clientID = clientID
        self._setup_sim_camera()

    def _euler2rotm(self,theta):
        """
            -- Get rotation matrix from euler angles
        """
        R_x = np.array([[1,         0,                  0                   ],
                        [0,         math.cos(theta[0]), -math.sin(theta[0]) ],
                        [0,         math.sin(theta[0]), math.cos(theta[0])  ]
                        ])
        R_y = np.array([[math.cos(theta[1]),    0,      math.sin(theta[1])  ],
                        [0,                     1,      0                   ],
                        [-math.sin(theta[1]),   0,      math.cos(theta[1])  ]
                        ])         
        R_z = np.array([[math.cos(theta[2]),    -math.sin(theta[2]),    0],
                        [math.sin(theta[2]),    math.cos(theta[2]),     0],
                        [0,                     0,                      1]
                        ])            
        R = np.dot(R_z, np.dot( R_y, R_x ))
        return R

    def _setup_sim_camera(self):
        """
            -- Get some param and handles from the simulation scene
            and set necessary parameter for camera
        """
        # Get handle to camera
        _, self.cam_handle = vrep.simxGetObjectHandle(self.clientID, self.Camera_NAME, vrep.simx_opmode_oneshot_wait)
        _, self.kinectRGB_handle = vrep.simxGetObjectHandle(self.clientID, self.Camera_RGB_NAME, vrep.simx_opmode_oneshot_wait)
        _, self.kinectDepth_handle = vrep.simxGetObjectHandle(self.clientID, self.Camera_DEPTH_NAME, vrep.simx_opmode_oneshot_wait)
        # Get camera pose and intrinsics in simulation
        _, cam_position = vrep.simxGetObjectPosition(self.clientID, self.cam_handle, -1, vrep.simx_opmode_oneshot_wait)
        _, cam_orientation = vrep.simxGetObjectOrientation(self.clientID, self.cam_handle, -1, vrep.simx_opmode_oneshot_wait)

        self.cam_trans = np.eye(4,4)
        self.cam_trans[0:3,3] = np.asarray(cam_position)
        self.cam_orientation = [-cam_orientation[0], -cam_orientation[1], -cam_orientation[2]]
        self.cam_rotm = np.eye(4,4)
        self.cam_rotm[0:3,0:3] = np.linalg.inv(self._euler2rotm(cam_orientation))
        self.cam_pose = np.dot(self.cam_trans, self.cam_rotm) # Compute rigid transformation representating camera pose

    def get_camera_data(self):
        """
            -- Read images data from vrep and convert into np array
        """
        # Get color image from simulation
        res, resolution, raw_image = vrep.simxGetVisionSensorImage(self.clientID, self.kinectRGB_handle, 0, vrep.simx_opmode_oneshot_wait)
        self._error_catch(res)
        color_img = np.array(raw_image, dtype=np.uint8)
        color_img.shape = (resolution[1], resolution[0], 3)
        color_img = color_img.astype(np.float)/255
        color_img[color_img < 0] += 1
        color_img *= 255
        color_img = np.fliplr(color_img)
        color_img = color_img.astype(np.uint8)

        # Get depth image from simulation
        res, resolution, depth_buffer = vrep.simxGetVisionSensorDepthBuffer(self.clientID, self.kinectDepth_handle, vrep.simx_opmode_oneshot_wait)
        self._error_catch(res)
        depth_img = np.array(depth_buffer)
        depth_img.shape = (resolution[1], resolution[0])
        depth_img = np.fliplr(depth_img)
        # zNear = 0.01
        # zFar = 10
        # depth_img = depth_img * (zFar - zNear) + zNear
        depth_img = (depth_img - self.Dis_NEAR)/self.Dis_FAR * self.INT16
        return depth_img, color_img

    def save_image(self, cur_depth, cur_color, currCmdTime, Save_IMG = True):
        """
            -- Save Color&Depth images
        """
        if Save_IMG:
            img = Image.fromarray(cur_color.astype('uint8')).convert('RGB')
            img_path = self.Save_PATH_COLOR + str(currCmdTime) + '_Rgb.png'
            img.save(img_path)
            depth_img = Image.fromarray(cur_depth.astype(np.uint32),mode='I')
            depth_path = self.Save_PATH_DEPTH + str(currCmdTime) + '_Depth.png'
            depth_img.save(depth_path)
            print("Succeed to save current images")
            return depth_path, img_path
        else:
            print("Skip saving images this time")

    def _error_catch(self, res):
        """
            -- Deal with error unexcepted
        """
        if res == vrep.simx_return_ok:
            print ("--- Image Exist!!!")
        elif res == vrep.simx_return_novalue_flag:
            print ("--- No image yet")
        else:
            print ("--- Error Raise")

"""
    Import const
"""
Simu_STEP = 2
Lua_PATH = r'../model/infer.lua'
Save_PATH_RES = r'./affordance/'
Save_PATH_AFFIMG = r'./affimg/'

def main():
    ur5 = UR5()
    ur5.connect();
    clientID = ur5.get_clientID()
    camera = Camera(clientID)

    lastCmdTime = vrep.simxGetLastCmdTime(clientID)
    vrep.simxSynchronousTrigger(clientID)

    count = 0
    while vrep.simxGetConnectionId(clientID) != -1 and count < Simu_STEP:
        currCmdTime=vrep.simxGetLastCmdTime(clientID)
        dt = currCmdTime - lastCmdTime

        # Camera achieve data
        cur_depth, cur_color = camera.get_camera_data()
        cur_depth_path, cur_img_path = camera.save_image(cur_depth, cur_color, currCmdTime)

        # Call affordance map function
        affordance_cmd = 'th ' + Lua_PATH + ' -imgColorPath ' + cur_img_path + ' -imgDepthPath ' + cur_depth_path + ' -resultPath ' + Save_PATH_RES + str(currCmdTime) + '_results.h5'
        try:
            os.system(affordance_cmd)
            print('-- Successfully create affordance map!')
        except:
            print('!!!!!!!!!!!!!!!!!!!!!!!!  Error occurred during creating affordance map')
        
        hdf2affimg(Save_PATH_RES + str(currCmdTime) + '_results.h5', currCmdTime)
        # Move ur5 
        # TODO:
        location = random.randint(100, 200, (1, 3)) 
        location = location[0] / 400
        print("UR5 Move to %s" %(location))
        ur5.ur5moveto(location[0], location[1], location[2])
        count += 1

        lastCmdTime=currCmdTime
        vrep.simxSynchronousTrigger(clientID)
        vrep.simxGetPingTime(clientID)

    ur5.disconnect()

def hdf2affimg(filename, currCmdTime):
    """
        Convert hdf5 file(output of affordance map network in lua) to img
    """
    h = h5py.File(filename,'r')

    res = h['results']
    res = np.array(res)
    res = res[0,1,:,:]
    resresize = 255.0 * cv.resize(res, (512,424), interpolation=cv.INTER_CUBIC)

    affimg_path = Save_PATH_AFFIMG + str(currCmdTime) + '_affimg.png'
    cv.imwrite(affimg_path, resresize)

if __name__ == '__main__':
    main()
