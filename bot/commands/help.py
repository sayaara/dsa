# -*- coding: utf-8 -*-
"""
===================================
Help command
===================================

Shows the list of available commands and how to use them.
"""

from typing import List

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse


class HelpCommand(BotCommand):
    """
    Help command
    
    Shows the list of all available commands and how to use them.
    Can also show detailed help for one specific command.
    
    Usage:
        /help         - show every command
        /help analyze - show detailed help for the analyze command
    """
    
    @property
    def name(self) -> str:
        return "help"
    
    @property
    def aliases(self) -> List[str]:
        return ["h", "帮助", "?"]
    
    @property
    def description(self) -> str:
        return "Show help"
    
    @property
    def usage(self) -> str:
        return "/help [command]"
    
    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """Run the help command"""
        # Deferred import to avoid a circular dependency
        from bot.dispatcher import get_dispatcher
        
        dispatcher = get_dispatcher()
        
        # When a command name is given, show detailed help for that command
        if args:
            cmd_name = args[0]
            command = dispatcher.get_command(cmd_name)
            
            if command is None:
                return BotResponse.error_response(f"Unknown command: {cmd_name}")
            
            # Build the detailed help
            help_text = self._format_command_help(command, dispatcher.command_prefix)
            return BotResponse.markdown_response(help_text)
        
        # Show the full command list
        commands = dispatcher.list_commands(include_hidden=False)
        prefix = dispatcher.command_prefix
        
        help_text = self._format_help_list(commands, prefix)
        return BotResponse.markdown_response(help_text)
    
    def _format_help_list(self, commands: List[BotCommand], prefix: str) -> str:
        """Format the command list"""
        lines = [
            "📚 **Stock Analysis Assistant - Command Help**",
            "",
            "Available commands:",
            "",
        ]
        
        for cmd in commands:
            # Command name and aliases
            aliases_str = ""
            if cmd.aliases:
                # Filter out non-ASCII aliases and show only the ASCII ones
                en_aliases = [a for a in cmd.aliases if a.isascii()]
                if en_aliases:
                    aliases_str = f" ({', '.join(prefix + a for a in en_aliases[:2])})"
            
            lines.append(f"• {prefix}{cmd.name}{aliases_str} - {cmd.description}")
            lines.append("")

        lines.extend([
            "",
            "---",
            f"💡 Enter {prefix}help <command> for details",
            "",
            "**Examples:**",
            "",
            f"• {prefix}analyze 301023 - 奕帆传动",
            "",
            f"• {prefix}market - Run the market review",
            "",
            f"• {prefix}batch - Analyze the watchlist in batch",
        ])
        
        return "\n".join(lines)
    
    def _format_command_help(self, command: BotCommand, prefix: str) -> str:
        """Format the detailed help for a single command"""
        lines = [
            f"📖 **{prefix}{command.name}** - {command.description}",
            "",
            f"**Usage:** `{command.usage}`",
            "",
        ]
        
        # Aliases
        if command.aliases:
            aliases = [f"`{prefix}{a}`" if a.isascii() else f"`{a}`" for a in command.aliases]
            lines.append(f"**Aliases:** {', '.join(aliases)}")
            lines.append("")
        
        # Permissions
        if command.admin_only:
            lines.append("⚠️ **Requires admin permission**")
            lines.append("")
        
        return "\n".join(lines)
