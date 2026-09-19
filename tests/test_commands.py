from types import SimpleNamespace

from orderui.commands import command_catalogue


def descriptor(identity, **kwargs):
    return {
        "handler_full_name": identity,
        "effective_command": identity,
        "module_path": "plugin",
        "enabled": True,
        "permission": "everyone",
        **kwargs,
    }


def test_flattened_nested_groups_inherit_permission_and_enablement():
    commands = [
        descriptor("parent", enabled=False, permission="admin"),
        descriptor(
            "group",
            parent_group_handler="parent",
            sub_commands=[descriptor("child", parent_group_handler="group")],
        ),
    ]
    result = {c["handler_full_name"]: c for c in command_catalogue(commands, {})}
    assert not result["child"]["enabled"]
    assert result["child"]["permission"] == "admin"


def test_disabled_plugin_commands_are_not_offered_as_enabled():
    result = command_catalogue([descriptor("help")], {"plugin": SimpleNamespace(activated=False)})
    assert not result[0]["enabled"]
