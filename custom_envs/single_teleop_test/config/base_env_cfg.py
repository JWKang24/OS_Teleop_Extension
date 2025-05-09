from __future__ import annotations

import math

from orbit.surgical.assets import ORBITSURGICAL_ASSETS_DATA_DIR

import omni.isaac.lab.sim as sim_utils
from omni.isaac.lab.assets import RigidObjectCfg, DeformableObjectCfg
from omni.isaac.lab.assets import AssetBaseCfg
from omni.isaac.lab.managers import EventTermCfg as EventTerm
from omni.isaac.lab.managers import SceneEntityCfg
from omni.isaac.lab.sensors import CameraCfg, FrameTransformerCfg
from omni.isaac.lab.sim.schemas.schemas_cfg import RigidBodyPropertiesCfg, DeformableBodyPropertiesCfg
from omni.isaac.lab.sim.spawners.from_files.from_files_cfg import UsdFileCfg
from omni.isaac.lab.sim.spawners.shapes.shapes_cfg import CuboidCfg
from omni.isaac.lab.sim.spawners.materials.physics_materials_cfg import RigidBodyMaterialCfg, DeformableBodyMaterialCfg
from omni.isaac.lab.sim.spawners.materials.visual_materials_cfg import PreviewSurfaceCfg
from omni.isaac.lab.sim.spawners.materials.visual_materials import spawn_preview_surface
from omni.isaac.lab.sim.spawners.meshes.meshes_cfg import MeshCuboidCfg
from omni.isaac.lab.utils import configclass

import custom_envs.single_teleop_test.mdp as mdp
from custom_envs.single_teleop_test.single_teleop_env_cfg import SingleTeleopEnvCfg

##
# Pre-defined configs
##
from omni.isaac.lab.markers.config import FRAME_MARKER_CFG  # isort: skip
from orbit.surgical.assets.psm import PSM_CFG  # isort: skip
from orbit.surgical.assets.ecm import ECM_CFG  # isort: skip

# def apply_preview_surface(prim_path, diffuse_color=(0.18, 0.18, 0.18), roughness=0.5, metallic=0.0):
            
#             material_cfg = PreviewSurfaceCfg(
#                 diffuse_color=diffuse_color,
#                 roughness=roughness,
#                 metallic=metallic,
#             )
#             return spawn_preview_surface(prim_path, material_cfg)

##
# Environment configuration
##


@configclass
class SingleTeleopBaseEnv(SingleTeleopEnvCfg):
    def __post_init__(self):
        # post init of parent
        super().__post_init__()

        # simulation settings
        self.viewer.eye = (0.0, 0.5, 0.2)
        self.viewer.lookat = (0.0, 0.0, 0.05)
        self.scene.replicate_physics = False

        # self.scene.table = AssetBaseCfg(
        #     prim_path="{ENV_REGEX_NS}/Table",
        #     spawn=sim_utils.UsdFileCfg(
        #         usd_path=f"{ORBITSURGICAL_ASSETS_DATA_DIR}/Props/Table/table.usd",
        #     ),
        #     init_state=AssetBaseCfg.InitialStateCfg(pos=(0.0, 0.0, -0.457)),
        # )

        # --- Define the table spawn configuration ---
        cfg_table = sim_utils.UsdFileCfg(
            usd_path=f"{ORBITSURGICAL_ASSETS_DATA_DIR}/Props/Table/table.usd",
            # scale=(1.0, 1.0, 1.0),  # Optional: specify if needed
        )

        # --- Spawn the table manually ---
        cfg_table.func(
            prim_path="/World/Objects/Table",
            cfg=cfg_table,
            translation=(0.0, 0.0, -0.457),  # Set table height correctly
            orientation=(1.0, 0.0, 0.0, 0.0),
        )

        # --- Set the table into the scene config to satisfy validation ---
        self.scene.table = AssetBaseCfg(
            prim_path="/World/Objects/Table",
            spawn=None,  # Already spawned manually above
        )


        # Define the cube and register it to the scene
        self.scene.cube_rigid = RigidObjectCfg(
            prim_path="/World/Objects/CubeRigid",
            init_state=RigidObjectCfg.InitialStateCfg(
                pos=(0.0, 0.0, 0.0),
                rot=(1.0, 0.0, 0.0, 0.0),
            ),
            spawn=sim_utils.CuboidCfg(
                size=(0.03, 0.004, 0.004),
                rigid_props=sim_utils.RigidBodyPropertiesCfg(
                    linear_damping=0.05,
                    angular_damping=0.05,
                    solver_position_iteration_count=30,
                    solver_velocity_iteration_count=10,
                ),
                mass_props=sim_utils.MassPropertiesCfg(
                    mass=0.01,
                ),
                collision_props=sim_utils.CollisionPropertiesCfg(
                    contact_offset=0.005,
                    rest_offset=-0.001,
                ),
                visual_material=PreviewSurfaceCfg(
                    diffuse_color=(0.8, 0.0, 0.0),
                    roughness=0.4,
                    metallic=0.0,
                    opacity=1.0,
                ),
                physics_material=sim_utils.RigidBodyMaterialCfg(
                    static_friction=3.0,
                    dynamic_friction=3.0,
                    restitution=0.0,
                ),
            )
        )


        # # Define the deformable cube
        # cfg_cube_deformable = MeshCuboidCfg(
        #     size=(0.025, 0.004, 0.004),
        #     deformable_props=DeformableBodyPropertiesCfg(
        #         solver_position_iteration_count=16,
        #         vertex_velocity_damping=0.1,
        #         contact_offset=0.0003,
        #         rest_offset=-0.0002,
        #         simulation_hexahedral_resolution=9,

        #     ),

        #     mass_props=sim_utils.MassPropertiesCfg(
        #         mass=0.01,
        #     ),
        #     visual_material=PreviewSurfaceCfg(
        #         diffuse_color=(0.8, 0.0, 0.0),
        #         roughness=0.6,
        #         metallic=0.0,
        #         opacity=1.0,
        #     ),
        #     physics_material=DeformableBodyMaterialCfg(
        #         dynamic_friction=3.0,
        #         youngs_modulus=100000000000.0,
        #         poissons_ratio=0.45,
        #         elasticity_damping=0.02,
        #         damping_scale=1.0,
        #     ),
        # )

        # cfg_cube_deformable.func(
        #     "/World/Objects/CubeDeformable",
        #     cfg_cube_deformable,
        #     translation=(0.0, 0.0, 0.0),
        #     orientation=(1.0, 0.0, 0.0, 0.0),
        # )

        # Define the deformable cube and register it to the scene
        # self.scene.cube_deformable = DeformableObjectCfg(
        #     prim_path="/World/Objects/CubeDeformable",
        #     init_state=DeformableObjectCfg.InitialStateCfg(
        #         pos=(0.0, 0.0, 0.0),
        #         rot=(1.0, 0.0, 0.0, 0.0),
        #     ),
        #     spawn=sim_utils.MeshCuboidCfg(
        #         size=(0.03, 0.002, 0.002),
        #         deformable_props=DeformableBodyPropertiesCfg(
        #             solver_position_iteration_count=16,
        #             vertex_velocity_damping=0.1,
        #             contact_offset=0.0003,
        #             rest_offset=0.0002,
        #             simulation_hexahedral_resolution=12,  # resolution of FEM mesh
        #         ),
        #         mass_props=sim_utils.MassPropertiesCfg(
        #             mass=0.003,
        #         ),
        #         visual_material=PreviewSurfaceCfg(
        #             diffuse_color=(0.8, 0.0, 0.0),
        #             roughness=0.4,
        #             metallic=0.0,
        #             opacity=1.0,
        #         ),
        #         physics_material=DeformableBodyMaterialCfg(
        #             dynamic_friction=3.0,         # approximates gripping
        #             youngs_modulus=5e9,           # stiffness
        #             poissons_ratio=0.47,          # compressibility
        #             elasticity_damping=0.02,      # energy dissipation
        #             damping_scale=1.0,
        #         ),
        #     )
        # )
        

        # sensors
        self.scene.camera_left = CameraCfg(
            prim_path="{ENV_REGEX_NS}/Robot_4/ecm_end_link/camera_left",
            update_period=0.1,
            height=480,
            width=640,
            data_types=["rgb"],
            spawn=sim_utils.PinholeCameraCfg(
                focal_length=24.0, focus_distance=400.0, horizontal_aperture=20.955, clipping_range=(0.1, 1.0e5)
            ),
            offset=CameraCfg.OffsetCfg(
                pos=(0.0, -2.75e-3, 0.0), rot=(0.7071068, 0.0, 0.0, 0.7071068), convention="ros"
            ),
        )

        self.scene.camera_right = CameraCfg(
            prim_path="{ENV_REGEX_NS}/Robot_4/ecm_end_link/camera_right",
            update_period=0.1,
            height=480,
            width=640,
            data_types=["rgb"],
            spawn=sim_utils.PinholeCameraCfg(
                focal_length=24.0, focus_distance=400.0, horizontal_aperture=20.955, clipping_range=(0.1, 1.0e5)
            ),
            offset=CameraCfg.OffsetCfg(pos=(0.0, 2.75e-3, 0.0), rot=(0.7071068, 0.0, 0.0, 0.7071068), convention="ros"),
        )
        
        # switch robot to PSM
        self.scene.robot_1 = PSM_CFG.replace(prim_path="{ENV_REGEX_NS}/Robot_1")
        self.scene.robot_1.init_state.pos = (0.17, 0.0, 0.15)
        self.scene.robot_1.init_state.rot = (1.0, 0.0, 0.0, 0.0)
        self.scene.robot_2 = PSM_CFG.replace(prim_path="{ENV_REGEX_NS}/Robot_2")
        self.scene.robot_2.init_state.pos = (-0.17, 0.0, 0.15)
        self.scene.robot_2.init_state.rot = (1.0, 0.0, 0.0, 0.0)
        self.scene.robot_3 = PSM_CFG.replace(prim_path="{ENV_REGEX_NS}/Robot_3")
        self.scene.robot_3.init_state.pos = (0.0, -0.10, 0.15)
        self.scene.robot_3.init_state.rot = (1.0, 0.0, 0.0, 0.0)
        self.scene.robot_4 = ECM_CFG.replace(prim_path="{ENV_REGEX_NS}/Robot_4")
        self.scene.robot_4.init_state.pos = (0.0, 0.45, 0.45)
        self.scene.robot_4.init_state.rot = (0.9238795, -0.3826834, 0, 0)

        # override actions
        self.actions.arm_1_action = mdp.JointPositionActionCfg(
            asset_name="robot_1",
            joint_names=[
                "psm_yaw_joint",
                "psm_pitch_end_joint",
                "psm_main_insertion_joint",
                "psm_tool_roll_joint",
                "psm_tool_pitch_joint",
                "psm_tool_yaw_joint",
            ],
            scale=1.0,
            use_default_offset=True,
        )
        self.actions.gripper_1_action = mdp.BinaryJointPositionActionCfg(
            asset_name="robot_1",
            joint_names=["psm_tool_gripper.*_joint"],
            open_command_expr={"psm_tool_gripper1_joint": -0.5, "psm_tool_gripper2_joint": 0.5},
            close_command_expr={"psm_tool_gripper1_joint": -0.15, "psm_tool_gripper2_joint": 0.15},
        )
        self.actions.arm_2_action = mdp.JointPositionActionCfg(
            asset_name="robot_2",
            joint_names=[
                "psm_yaw_joint",
                "psm_pitch_end_joint",
                "psm_main_insertion_joint",
                "psm_tool_roll_joint",
                "psm_tool_pitch_joint",
                "psm_tool_yaw_joint",
            ],
            scale=1.0,
            use_default_offset=True,
        )
        self.actions.gripper_2_action = mdp.BinaryJointPositionActionCfg(
            asset_name="robot_2",
            joint_names=["psm_tool_gripper.*_joint"],
            open_command_expr={"psm_tool_gripper1_joint": -0.5, "psm_tool_gripper2_joint": 0.5},
            close_command_expr={"psm_tool_gripper1_joint": -0.15, "psm_tool_gripper2_joint": 0.15},
        )

