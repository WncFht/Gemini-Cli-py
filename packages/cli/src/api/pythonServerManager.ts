import { ChildProcessWithoutNullStreams, spawn } from 'child_process';
import path from 'path';

export class PythonServerManager {
  private process: ChildProcessWithoutNullStreams | null = null;
  private readyPromise: Promise<void>;
  private resolveReady: () => void = () => {};
  private rejectReady: (reason?: any) => void = () => {};

  constructor(private corePackagePath: string) {
    this.readyPromise = new Promise((resolve, reject) => {
      this.resolveReady = resolve;
      this.rejectReady = reject;
    });
  }

  start(): void {
    if (this.process) {
      console.log('Python server is already running.');
      return;
    }

    const cwd = path.resolve(this.corePackagePath);

    // Using 'uv' as specified in the Makefile
    this.process = spawn('uv', ['run', 'uvicorn', 'gemini_cli_core.server:app'], {
      cwd,
      // Create a detached process group that can be killed entirely
      detached: true,
    });

    this.process.stdout.on('data', (data: Buffer) => {
      const output = data.toString();
      console.log(`[Python Server]: ${output}`);
      if (output.includes('Application startup complete')) {
        this.resolveReady();
      }
    });

    this.process.stderr.on('data', (data: Buffer) => {
      const error = data.toString();
      console.error(`[Python Server ERROR]: ${error}`);
      // If server fails to start, reject the promise
      this.rejectReady(new Error(`Python server failed to start: ${error}`));
    });

    this.process.on('close', (code: number | null) => {
      console.log(`Python server process exited with code ${code}`);
      this.process = null;
      // If it closes before ready, reject promise
      this.rejectReady(new Error(`Python server exited prematurely with code ${code}`));
    });
  }

  // Returns a promise that resolves when the server is ready to accept connections
  ready(): Promise<void> {
    return this.readyPromise;
  }

  stop(): void {
    if (this.process && this.process.pid) {
      console.log('Stopping Python server...');
      // Kill the entire process group
      process.kill(-this.process.pid, 'SIGKILL');
      this.process = null;
    }
  }
} 