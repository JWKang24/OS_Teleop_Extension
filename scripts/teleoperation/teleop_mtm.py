import argparse

from omni.isaac.lab.app import AppLauncher

# add argparse arguments
parser = argparse.ArgumentParser(description="MTM teleoperation for Custom MultiArm dVRK environments.")
parser.add_argument(
    "--disable_fabric", action="store_true", default=False, help="Disable fabric and use USD I/O operations."
)
parser.add_argument("--num_envs", type=int, default=1, help="Number of environments to simulate.")
parser.add_argument("--task", type=str, default="Isaac-MTM-Teleop-v0", help="Name of the task.")
parser.add_argument("--scale", type=float, default=0.4, help="Teleop scaling factor.")
parser.add_argument("--is_simulated", type=bool, default=False, help="Whether the MTM input is from the simulated model or not.")
parser.add_argument("--enable_logging", type=bool, default=False, help="Whether to log the teleoperation output or not.")

# append AppLauncher cli args
AppLauncher.add_app_launcher_args(parser)
# parse the arguments
args_cli = parser.parse_args()

# launch omniverse app
app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

"""Rest everything follows."""


import gymnasium as gym
import torch

import carb

from omni.isaac.lab_tasks.utils import parse_env_cfg

import cv2
from scipy.spatial.transform import Rotation as R
import numpy as np
import time
from datetime import datetime

import omni.kit.viewport.utility as vp_utils
import omni.kit.commands
from tf_utils import pose_to_transformation_matrix, transformation_matrix_to_pose
from logger_utils import CSVLogger

import sys
import os
sys.path.append(os.path.abspath("."))
from teleop_interface.MTM.se3_mtm import MTMTeleop
from teleop_interface.MTM.mtm_manipulator import MTMManipulator
import custom_envs

# map mtm gripper joint angle to psm jaw gripper angles in simulation
def get_jaw_gripper_angles(gripper_command, env, robot_name="robot_1"):
    if gripper_command is None:
        gripper1_joint_angle = env.unwrapped[robot_name].data.joint_pos[0][-2].cpu().numpy()
        gripper2_joint_angle = env.unwrapped[robot_name].data.joint_pos[0][-1].cpu().numpy()
        return np.array([gripper1_joint_angle, gripper2_joint_angle])
    # input: -1.72 (closed), 1.06 (opened)
    # output: 0,0 (closed), -0.52359, 0.52359 (opened)
    gripper2_angle = 0.52359 / (1.06 + 1.72) * (gripper_command + 1.72)
    return np.array([-gripper2_angle, gripper2_angle])


# process cam_T_psmtip to psmbase_T_psmtip and make usuable action input
def process_actions(cam_T_psm1, w_T_psm1base, cam_T_psm2, w_T_psm2base, w_T_cam, env, gripper1_command, gripper2_command) -> torch.Tensor:
    """Process actions for the environment."""
    psm1base_T_psm1 = np.linalg.inv(w_T_psm1base)@w_T_cam@cam_T_psm1
    psm2base_T_psm2 = np.linalg.inv(w_T_psm2base)@w_T_cam@cam_T_psm2
    psm1_rel_pos, psm1_rel_quat = transformation_matrix_to_pose(psm1base_T_psm1)
    psm2_rel_pos, psm2_rel_quat = transformation_matrix_to_pose(psm2base_T_psm2)
    actions = np.concatenate([psm1_rel_pos, psm1_rel_quat, get_jaw_gripper_angles(gripper1_command, env, 'robot_1'),
                              psm2_rel_pos, psm2_rel_quat, get_jaw_gripper_angles(gripper2_command, env, 'robot_2')])
    actions = torch.tensor(actions, device=env.unwrapped.device).repeat(env.unwrapped.num_envs, 1)
    return actions


def main():
    is_simulated = args_cli.is_simulated
    scale=args_cli.scale
    enable_logging = args_cli.enable_logging

    psm_name_dict = {
        "PSM1": "robot_1",
        "PSM2": "robot_2"
    }

    if enable_logging:
        # Create a unique folder for this run
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_folder = os.path.join(os.getcwd(), f"teleop_logs_{timestamp}")
        os.makedirs(run_folder, exist_ok=True)

        # Initialize logger
        log_file_path = os.path.join(run_folder, "teleop_log.csv")
        logger = CSVLogger(log_file_path, psm_name_dict)

        frame_num = 0
        cam_stabilized = False

    # Setup the MTM in the real world
    mtm_manipulator = MTMManipulator()
    mtm_manipulator.home()

    # parse configuration
    env_cfg = parse_env_cfg(
        args_cli.task, device=args_cli.device, num_envs=args_cli.num_envs, use_fabric=not args_cli.disable_fabric
    )
    # modify configuration
    env_cfg.terminations.time_out = None

    # create environment
    env = gym.make(args_cli.task, cfg=env_cfg)
    env.reset()

    teleop_interface = MTMTeleop(is_simulated=is_simulated)
    teleop_interface.reset()

    camera_l = env.unwrapped.scene["camera_left"]
    camera_r = env.unwrapped.scene["camera_right"]

    if not is_simulated:
        view_port_l = vp_utils.create_viewport_window("Left Camera", width = 800, height = 600)
        view_port_l.viewport_api.camera_path = '/World/envs/env_0/Robot_4/ecm_end_link/camera_left' #camera_l.cfg.prim_path

        view_port_r = vp_utils.create_viewport_window("Right Camera", width = 800, height = 600)
        view_port_r.viewport_api.camera_path = '/World/envs/env_0/Robot_4/ecm_end_link/camera_right' #camera_r.cfg.prim_path

    psm1 = env.unwrapped.scene[psm_name_dict["PSM1"]]
    psm2 = env.unwrapped.scene[psm_name_dict["PSM2"]]

    mtm_orientation_matched = False
    was_in_clutch = True
    init_mtml_position = None
    init_psm1_tip_position = None
    init_mtmr_position = None
    init_psm2_tip_position = None

    # simulate environment
    while simulation_app.is_running():
        start_time = time.time()

        # process actions
        camera_l_pos = camera_l.data.pos_w
        camera_r_pos = camera_r.data.pos_w
        # get center of both cameras
        str_camera_pos = (camera_l_pos + camera_r_pos) / 2
        camera_quat = camera_l.data.quat_w_world  # forward x, up z
        world_T_cam = pose_to_transformation_matrix(str_camera_pos.cpu().numpy()[0], camera_quat.cpu().numpy()[0])
        cam_T_world = np.linalg.inv(world_T_cam)

        if not mtm_orientation_matched:
            print("Start matching orientation of MTM with the PSMs in the simulation. May take a few seconds.")
            mtm_orientation_matched = True
            psm1_tip_pose_w = psm1.data.body_link_pos_w[0][-1].cpu().numpy()
            psm1_tip_quat_w = psm1.data.body_link_quat_w[0][-1].cpu().numpy()
            world_T_psm1tip = pose_to_transformation_matrix(psm1_tip_pose_w, psm1_tip_quat_w)
            hrsv_T_mtml = teleop_interface.simpose2hrsvpose(cam_T_world @ world_T_psm1tip)

            psm2_tip_pose_w = psm2.data.body_link_pos_w[0][-1].cpu().numpy()
            psm2_tip_quat_w = psm2.data.body_link_quat_w[0][-1].cpu().numpy()
            world_T_psm2tip = pose_to_transformation_matrix(psm2_tip_pose_w, psm2_tip_quat_w)
            hrsv_T_mtmr = teleop_interface.simpose2hrsvpose(cam_T_world @ world_T_psm2tip)

            mtm_manipulator.adjust_orientation(hrsv_T_mtml, hrsv_T_mtmr)
            print("Initial orientation matched. Start teleoperation by pressing and releasing the clutch button.")
            continue

        # get target pos, rot in camera view with joint and clutch commands
        mtml_pos, mtml_rot, l_gripper_joint, mtmr_pos, mtmr_rot, r_gripper_joint, clutch, mono = teleop_interface.advance()
        if not l_gripper_joint:
            time.sleep(0.05)
            continue

        # stop teleoperation if mono button is pressed
        if mono:
            print("Mono button pressed. Stopping teleoperation.")
            mtm_manipulator.hold_position()
            break

        mtml_orientation = R.from_rotvec(mtml_rot).as_quat()
        mtml_orientation = np.concatenate([[mtml_orientation[3]], mtml_orientation[:3]])
        mtmr_orientation = R.from_rotvec(mtmr_rot).as_quat()
        mtmr_orientation = np.concatenate([[mtmr_orientation[3]], mtmr_orientation[:3]])

        psm1_base_link_pos = psm1.data.body_link_pos_w[0][0].cpu().numpy()
        psm1_base_link_quat = psm1.data.body_link_quat_w[0][0].cpu().numpy()
        world_T_psm1_base = pose_to_transformation_matrix(psm1_base_link_pos, psm1_base_link_quat)

        psm2_base_link_pos = psm2.data.body_link_pos_w[0][0].cpu().numpy()
        psm2_base_link_quat = psm2.data.body_link_quat_w[0][0].cpu().numpy()
        world_T_psm2_base = pose_to_transformation_matrix(psm2_base_link_pos, psm2_base_link_quat)

        if not clutch:
            if was_in_clutch:
                print("Released from clutch. Starting teleoperation again")
                init_mtml_position = mtml_pos
                psm1_tip_pose_w = psm1.data.body_link_pos_w[0][-1].cpu().numpy()
                psm1_tip_quat_w = psm1.data.body_link_quat_w[0][-1].cpu().numpy()
                world_T_psm1tip = pose_to_transformation_matrix(psm1_tip_pose_w, psm1_tip_quat_w)
                init_cam_T_psm1tip = cam_T_world @ world_T_psm1tip
                init_psm1_tip_position = init_cam_T_psm1tip[:3, 3]
                cam_T_psm1tip = pose_to_transformation_matrix(init_cam_T_psm1tip[:3, 3], mtml_orientation)

                init_mtmr_position = mtmr_pos
                psm2_tip_pose_w = psm2.data.body_link_pos_w[0][-1].cpu().numpy()
                psm2_tip_quat_w = psm2.data.body_link_quat_w[0][-1].cpu().numpy()
                world_T_psm2tip = pose_to_transformation_matrix(psm2_tip_pose_w, psm2_tip_quat_w)
                init_cam_T_psm2tip = cam_T_world @ world_T_psm2tip
                init_psm2_tip_position = init_cam_T_psm2tip[:3, 3]
                cam_T_psm2tip = pose_to_transformation_matrix(init_cam_T_psm2tip[:3, 3], mtmr_orientation)

                actions = process_actions(cam_T_psm1tip, world_T_psm1_base, cam_T_psm2tip, world_T_psm2_base, world_T_cam, env, l_gripper_joint, r_gripper_joint)
            else:
                # normal operation
                psm1_target_position = init_psm1_tip_position + (mtml_pos - init_mtml_position) * scale
                cam_T_psm1tip = pose_to_transformation_matrix(psm1_target_position, mtml_orientation)

                psm2_target_position = init_psm2_tip_position + (mtmr_pos - init_mtmr_position) * scale
                cam_T_psm2tip = pose_to_transformation_matrix(psm2_target_position, mtmr_orientation)
                
                actions = process_actions(cam_T_psm1tip, world_T_psm1_base, cam_T_psm2tip, world_T_psm2_base, world_T_cam, env, l_gripper_joint, r_gripper_joint)
            was_in_clutch = False
        
        else:  # clutch pressed: stop moving, set was_in_clutch to True
            was_in_clutch = True

            psm1_cur_eef_pos = psm1.data.body_link_pos_w[0][-1].cpu().numpy()
            psm1_cur_eef_quat = psm1.data.body_link_quat_w[0][-1].cpu().numpy()
            world_T_psm1_tip = pose_to_transformation_matrix(psm1_cur_eef_pos, psm1_cur_eef_quat)

            psm2_cur_eef_pos = psm2.data.body_link_pos_w[0][-1].cpu().numpy()
            psm2_cur_eef_quat = psm2.data.body_link_quat_w[0][-1].cpu().numpy()
            world_T_psm2_tip = pose_to_transformation_matrix(psm2_cur_eef_pos, psm2_cur_eef_quat)

            psm1_base_T_psm1_tip = np.linalg.inv(world_T_psm1_base) @ world_T_psm1_tip
            psm2_base_T_psm2_tip = np.linalg.inv(world_T_psm2_base) @ world_T_psm2_tip

            psm1_rel_pos, psm1_rel_quat = transformation_matrix_to_pose(psm1_base_T_psm1_tip)
            psm2_rel_pos, psm2_rel_quat = transformation_matrix_to_pose(psm2_base_T_psm2_tip)

            psm1_gripper1_joint_angle = psm1.data.joint_pos[0][-2].cpu().numpy()
            psm1_gripper2_joint_angle = psm1.data.joint_pos[0][-1].cpu().numpy()

            psm2_gripper1_joint_angle = psm2.data.joint_pos[0][-2].cpu().numpy()
            psm2_gripper2_joint_angle = psm2.data.joint_pos[0][-1].cpu().numpy()

            actions = np.concatenate([psm1_rel_pos, psm1_rel_quat, [psm1_gripper1_joint_angle, psm1_gripper2_joint_angle], 
                                      psm2_rel_pos, psm2_rel_quat, [psm2_gripper1_joint_angle, psm2_gripper2_joint_angle]])
            actions = torch.tensor(actions, device=env.unwrapped.device).repeat(env.unwrapped.num_envs, 1)

        env.step(actions)

        if enable_logging:
            # For Logging
            frame_num += 1
            if not cam_stabilized:
                if frame_num > 60:
                    # wait for 60 frames to stabilize the camera
                    cam_stabilized = True
                    frame_num = 0
                    print("Camera stabilized. Logging will start from the next frame.")
                continue

            robot_states = {}
            for psm, robot_name in psm_name_dict.items():
                robot = env.unwrapped.scene[robot_name]
                joint_positions = robot.data.joint_pos[0][:6].cpu().numpy()
                jaw_angle = abs(robot.data.joint_pos[0][-2].cpu().numpy()) + abs(robot.data.joint_pos[0][-1].cpu().numpy())
                ee_position = robot.data.body_link_pos_w[0][-1].cpu().numpy()
                ee_quat = robot.data.body_link_quat_w[0][-1].cpu().numpy()
                orientation_matrix = R.from_quat(np.concatenate([ee_quat[1:], [ee_quat[0]]])).as_matrix()

                robot_states[psm] = {
                    "joint_positions": joint_positions,
                    "jaw_angle": jaw_angle,
                    "ee_position": ee_position,
                    "orientation_matrix": orientation_matrix,
                }

            # Save camera images
            cam_l_input = camera_l.data.output["rgb"][0].cpu().numpy()
            cam_r_input = camera_r.data.output["rgb"][0].cpu().numpy()
            camera_left_path = os.path.join(run_folder, f"camera_left_{frame_num}.png")
            camera_right_path = os.path.join(run_folder, f"camera_right_{frame_num}.png")
            cv2.imwrite(camera_left_path, cam_l_input)
            cv2.imwrite(camera_right_path, cam_r_input)

            # Log data
            logger.log(frame_num, env.sim.current_time, robot_states, camera_left_path, camera_right_path)

        time.sleep(max(0.0, 1/30.0 - time.time() + start_time))

    # close the simulator
    env.close()


if __name__ == "__main__":
    # run the main function
    main()
    # close sim app
    simulation_app.close()
