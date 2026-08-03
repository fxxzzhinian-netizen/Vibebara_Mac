import { Command, CommanderError } from "commander";
import {
  loginCommand,
  logoutCommand,
  whoamiCommand,
} from "./commands/auth.js";
import {
  mergeCommand,
  pullCommand,
  pushCommand,
} from "./commands/collaboration.js";
import { statusCommand } from "./commands/status.js";
import { CliError, EXIT } from "./errors.js";
import { Output } from "./output.js";

interface GlobalOptions {
  json?: boolean;
  cwd?: string;
  verbose?: boolean;
  cloudApiBase?: string;
  yes?: boolean;
}

interface SelectorOptions {
  deployment?: string;
  skill?: string;
  project?: string;
}

function addSelectorOptions(command: Command): Command {
  return command
    .argument("[target]", "skill name when --skill is omitted")
    .option("--deployment <id>", "select an exact deployment id")
    .option("--skill <name>", "select by skill id or name")
    .option("--project <id>", "limit selection to a project");
}

export function createProgram(): Command {
  const program = new Command()
    .name("vibebara")
    .description("Headless Skill merge, push, and pull for Vibebara.")
    .version("0.1.0")
    .option("--json", "emit machine-readable JSON")
    .option("--cwd <path>", "override the working directory")
    .option("--verbose", "enable verbose diagnostics")
    .option("--yes", "skip confirmation prompts")
    .option("--cloud-api-base <url>", "override the cloud REST API base")
    .showHelpAfterError()
    .exitOverride();

  program
    .command("login")
    .description("validate and store a long-lived PAT")
    .option("--api-key <key>", "vhk_ personal access token")
    .option("--cloud <url>", "cloud REST API base")
    .action(async (options: { apiKey?: string; cloud?: string }) => {
      const globals = program.opts<GlobalOptions>();
      await loginCommand(
        {
          apiKey: options.apiKey,
          cloud: options.cloud ?? globals.cloudApiBase,
        },
        new Output(globals),
      );
    });

  program
    .command("whoami")
    .description("show the authenticated user")
    .action(async () => {
      const globals = program.opts<GlobalOptions>();
      await whoamiCommand(new Output(globals), globals.cloudApiBase);
    });

  program
    .command("logout")
    .description("remove the locally stored PAT")
    .action(() => {
      logoutCommand(new Output(program.opts<GlobalOptions>()));
    });

  program
    .command("status")
    .description("inspect all local skill deployments")
    .option("--project <id>", "filter by project id")
    .action(async (options: { project?: string }) => {
      const globals = program.opts<GlobalOptions>();
      await statusCommand(
        { ...options, cloudApiBase: globals.cloudApiBase },
        new Output(globals),
      );
    });

  addSelectorOptions(
    program
      .command("merge")
      .description("preview and apply an AI three-way merge"),
  )
    .option("--preview", "preview only; do not write")
    .option(
      "--force-manual",
      "submit even when manual conflicts or AI degradation exist",
    )
    .action(
      async (
        target: string | undefined,
        options: SelectorOptions & {
          preview?: boolean;
          forceManual?: boolean;
        },
      ) => {
        const globals = program.opts<GlobalOptions>();
        await mergeCommand(
          {
            ...options,
            skill: options.skill ?? target,
            cwd: globals.cwd,
            cloudApiBase: globals.cloudApiBase,
            yes: globals.yes,
          },
          new Output(globals),
        );
      },
    );

  addSelectorOptions(
    program.command("push").description("push local skill changes"),
  )
    .option("--create-version", "create a version snapshot after push")
    .option("--version-label <label>", "optional version label")
    .action(
      async (
        target: string | undefined,
        options: SelectorOptions & {
          createVersion?: boolean;
          versionLabel?: string;
        },
      ) => {
        const globals = program.opts<GlobalOptions>();
        await pushCommand(
          {
            ...options,
            skill: options.skill ?? target,
            cwd: globals.cwd,
            cloudApiBase: globals.cloudApiBase,
          },
          new Output(globals),
        );
      },
    );

  addSelectorOptions(
    program.command("pull").description("pull the latest team skill"),
  )
    .option("--overwrite", "overwrite unpushed local changes")
    .action(
      async (
        target: string | undefined,
        options: SelectorOptions & { overwrite?: boolean },
      ) => {
        const globals = program.opts<GlobalOptions>();
        await pullCommand(
          {
            ...options,
            skill: options.skill ?? target,
            cwd: globals.cwd,
            cloudApiBase: globals.cloudApiBase,
          },
          new Output(globals),
        );
      },
    );

  return program;
}

export async function run(argv: string[] = process.argv): Promise<void> {
  const program = createProgram();
  try {
    await program.parseAsync(argv);
  } catch (error) {
    if (
      error instanceof CommanderError &&
      (error.code === "commander.helpDisplayed" ||
        error.code === "commander.version")
    ) {
      return;
    }
    const globals = program.opts<GlobalOptions>();
    const output = new Output(globals);
    if (error instanceof CliError) {
      output.error(error.message, error.details);
      process.exitCode = error.exitCode;
      return;
    }
    if (error instanceof CommanderError) {
      output.error(error.message);
      process.exitCode = EXIT.USAGE;
      return;
    }
    output.error((error as Error)?.message || "未知错误");
    process.exitCode = EXIT.GENERAL;
  }
}
