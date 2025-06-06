#!/usr/bin/env python3
import rospy
import numpy as np
from omni_msgs.msg import OmniButtonEvent
from omni.isaac.lab.devices import DeviceBase
from scipy.spatial.transform.rotation import Rotation
from sensor_msgs.msg import JointState, Joy
from geometry_msgs.msg import PoseStamped

def transformation_matrix_to_pose(transformation_matrix):
    """
    Convert a 4x4 transformation matrix to position and quaternion.

    Args:
        transformation_matrix (np.ndarray): 4x4 transformation matrix.

    Returns:
        tuple: Position array (x, y, z) and quaternion array (w, x, y, z).
    """
    # Extract the translation part
    position = transformation_matrix[:3, 3]

    # Extract the rotation part and convert to quaternion
    rotation_matrix = transformation_matrix[:3, :3]
    quaternion = Rotation.from_matrix(rotation_matrix).as_quat()

    # Reorder quaternion to (w, x, y, z)
    quaternion = np.array([quaternion[3], quaternion[0], quaternion[1], quaternion[2]])

    return position, quaternion


def pose_to_transformation_matrix(position, quaternion):
    """
    Convert position and quaternion to a 4x4 transformation matrix.

    Args:
        position (np.ndarray): Position array (x, y, z).
        quaternion (np.ndarray): Quaternion array (w, x, y, z).

    Returns:
        np.ndarray: 4x4 transformation matrix.
    """
    # Create a 4x4 identity matrix
    transformation_matrix = np.eye(4)

    # Set the translation part
    transformation_matrix[:3, 3] = position

    # Convert quaternion to rotation matrix
    rotation_matrix = Rotation.from_quat([quaternion[1], quaternion[2], quaternion[3], quaternion[0]]).as_matrix()

    # Set the rotation part
    transformation_matrix[:3, :3] = rotation_matrix

    return transformation_matrix

class MTMTeleop(DeviceBase):
    def __init__(self, is_simulated=False):
        super().__init__()
        self.simulated = is_simulated

        # ROS node initialization
        if not rospy.core.is_initialized():
            rospy.init_node("mtm_teleop", anonymous=True)

        # State variables
        self.enabled = False
        self.clutch = True
        self.mono = False
        self.first_clutch_triggered = False
        self.reset_done = False

        self.mtml_pose = None
        self.mtmr_pose = None
        self.l_jaw_angle = None if not self.simulated else 0.5
        self.r_jaw_angle = None if not self.simulated else 0.5

        # === Pose Lock ===
        self.frozen_mtml_pose = None
        self.frozen_mtmr_pose = None
        self.use_frozen_pose = False

        # Transformation matrices to align orientation with the simulation
        self.hrsv_T_hrsv_sim = np.array([[0, 1, 0, 0],
                                         [0, 0, 1, 0],
                                         [1, 0, 0, 0],
                                         [0, 0, 0, 1]])
        self.hrsv_sim_T_hrsv = np.linalg.inv(self.hrsv_T_hrsv_sim)
        self.mtm_T_mtm_sim = np.array([[0, -1, 0, 0], 
                                       [-1, 0, 0, 0],
                                       [0, 0, -1, 0],
                                       [0, 0, 0, 1]])
        self.mtm_sim_T_mtm = np.linalg.inv(self.mtm_T_mtm_sim)

        rospy.Subscriber("/MTML/measured_cp", PoseStamped, self.mtml_callback)
        rospy.Subscriber("/MTMR/measured_cp", PoseStamped, self.mtmr_callback)
        rospy.Subscriber("/MTML/gripper/measured_js", JointState, self.mtml_gripper_callback)
        rospy.Subscriber("/MTMR/gripper/measured_js", JointState, self.mtmr_gripper_callback)
        rospy.Subscriber("/footpedals/clutch" if not self.simulated else "/console/clutch", Joy, self.clutch_callback)
        rospy.Subscriber("/footpedals/coag", Joy, self.mono_callback)

    def mtml_callback(self, msg):
        self.mtml_pose = msg.pose

    def mtmr_callback(self, msg):
        self.mtmr_pose = msg.pose
    
    def mtml_gripper_callback(self, msg):
        self.l_jaw_angle = msg.position[0]

    def mtmr_gripper_callback(self, msg):
        self.r_jaw_angle = msg.position[0]

    def clutch_callback(self, msg):
        if msg.buttons[0] == 1:
            if not self.enabled:
                self.enabled = True
                if not self.reset_done:
                    self.first_clutch_triggered = True  # Only set once
            self.clutch = True
            print("Clutch Pressed")
        elif msg.buttons[0] == 0:
            if not self.enabled:
                self.clutch = True
                print("Ignoring the clutch releasing output before the first clutch press")
            else:
                self.clutch = False
                print("Clutch Released")


    def mono_callback(self, msg):
        self.mono = msg.buttons[0] == 1

    def advance(self):
        """Retrieve the latest teleoperation command."""
        if not self.mtml_pose or not self.mtmr_pose or self.l_jaw_angle is None or self.r_jaw_angle is None:
            print("Waiting for subscription... Cannot start teleoperation yet")
            return None, None, None, None, None, None, None, None, None
        
        # === Freeze MTM Pose on First Clutch Press ===
        trigger_reset = self.first_clutch_triggered and not self.reset_done
        if trigger_reset:
            print("[MTM] Freezing MTM pose after first clutch press.")
            self.frozen_mtml_pose = self.mtml_pose
            self.frozen_mtmr_pose = self.mtmr_pose
            self.use_frozen_pose = True

        pose_mtml = self.frozen_mtml_pose if self.use_frozen_pose else self.mtml_pose
        pose_mtmr = self.frozen_mtmr_pose if self.use_frozen_pose else self.mtmr_pose

        # MTML
        hrsv_T_mtml = pose_to_transformation_matrix(
            np.array([self.mtml_pose.position.x, self.mtml_pose.position.y, self.mtml_pose.position.z]),
            np.array([self.mtml_pose.orientation.w, self.mtml_pose.orientation.x,
                      self.mtml_pose.orientation.y, self.mtml_pose.orientation.z])
        )
        hrsv_sim_T_mtml_sim = self.hrsv_sim_T_hrsv @ hrsv_T_mtml @ self.mtm_T_mtm_sim
        p_mtml, q_mtml = transformation_matrix_to_pose(hrsv_sim_T_mtml_sim)
        rvec_mtml = Rotation.from_quat(np.concatenate([q_mtml[1:], [q_mtml[0]]])).as_rotvec()

        # MTMR
        hrsv_T_mtmr = pose_to_transformation_matrix(
            np.array([self.mtmr_pose.position.x, self.mtmr_pose.position.y, self.mtmr_pose.position.z]),
            np.array([self.mtmr_pose.orientation.w, self.mtmr_pose.orientation.x,
                      self.mtmr_pose.orientation.y, self.mtmr_pose.orientation.z])
        )
        hrsv_sim_T_mtmr_sim = self.hrsv_sim_T_hrsv @ hrsv_T_mtmr @ self.mtm_T_mtm_sim
        p_mtmr, q_mtmr = transformation_matrix_to_pose(hrsv_sim_T_mtmr_sim)
        rvec_mtmr = Rotation.from_quat(np.concatenate([q_mtmr[1:], [q_mtmr[0]]])).as_rotvec()

        # Compute reset flag
        self.first_clutch_triggered = False  # reset after reporting once

        return (
            p_mtml, rvec_mtml, self.l_jaw_angle,
            p_mtmr, rvec_mtmr, self.r_jaw_angle,
            self.clutch, self.mono,
            trigger_reset
        )




    def reset(self):
        """Reset the teleoperation state."""
        self.clutch = True
        self.gripper_open = False

    def simpose2hrsvpose(self, cam_T_psm):
        return self.hrsv_T_hrsv_sim @ cam_T_psm @ self.mtm_sim_T_mtm
        
    def add_callback(self, key, func):
        """
        Adds a callback function triggered by a specific key input.
        """
        pass
