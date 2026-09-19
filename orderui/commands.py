"""Normalize host command descriptors, including flattened parent groups."""


def command_catalogue(commands, plugins):
    descriptors = {}

    def collect(command):
        descriptors[command["handler_full_name"]] = command
        for child in command.get("sub_commands", []):
            collect(child)

    for command in commands:
        collect(command)

    def flags(command, seen):
        identity = command["handler_full_name"]
        if identity in seen:
            return False, True, True
        enabled = bool(command.get("enabled"))
        admin = command.get("permission") == "admin"
        conflict = bool(command.get("has_conflict"))
        plugin = plugins.get(command.get("module_path"))
        if plugin is not None:
            enabled = enabled and plugin.activated
        parent = descriptors.get(command.get("parent_group_handler"))
        if parent:
            parent_enabled, parent_admin, parent_conflict = flags(parent, seen | {identity})
            enabled = enabled and parent_enabled
            admin = admin or parent_admin
            conflict = conflict or parent_conflict
        return enabled, admin, conflict

    result = []
    for command in descriptors.values():
        enabled, admin, conflict = flags(command, set())
        result.append(
            {
                key: command.get(key)
                for key in (
                    "handler_full_name",
                    "plugin",
                    "plugin_display_name",
                    "description",
                    "effective_command",
                    "aliases",
                    "is_group",
                )
            }
            | {
                "enabled": enabled,
                "permission": "admin" if admin else "everyone",
                "has_conflict": conflict,
            }
        )
    return result
