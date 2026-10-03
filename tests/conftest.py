import importlib

import pytest


@pytest.fixture
def load_module():
    def load(name):
        try:
            return importlib.import_module(f"agent_system.{name}")
        except ModuleNotFoundError as exc:
            if exc.name == f"agent_system.{name}":
                pytest.fail(f"Not implemented yet: agent_system.{name}")
            raise
    return load


@pytest.fixture
def action_data():
    return {
        "action_id": "a1", "shot_id": "s1", "plan_id": "p1",
        "source": "INITIAL", "action_name": "move_forward",
        "parameters": {"speed_level": "slow", "duration": 2.0},
        "registry_revision": "mock-v0",
    }


@pytest.fixture
def plan_data(action_data):
    return {
        "plan_id": "p1", "shot_id": "s1", "registry_revision": "mock-v0",
        "actions": [action_data], "execution_relation": "SEQUENTIAL",
    }


@pytest.fixture
def shot_data():
    return {
        "shot_id": "s1", "shot_goal": "Introduce the subject",
        "subject_action": "Stand still",
        "composition_target": {
            "target_center_x": 0.5, "target_center_y": 0.5,
            "tolerance_x": 0.1, "tolerance_y": 0.1,
        },
        "camera_motions": [{"motion": "push toward subject", "tempo": "slow"}],
        "execution_relation": "SEQUENTIAL", "expected_duration": 2.0,
    }
