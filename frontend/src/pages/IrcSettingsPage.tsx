import { useEffect, useState } from "react";
import {
  useConnectIrc,
  useCreateIrcSearchJob,
  useDisconnectIrc,
  useIrcDownloadJobs,
  useIrcSearchJobs,
  useIrcSettings,
  useIrcStatus,
  useUpdateIrcSettings,
} from "../api/irc";

export default function IrcSettingsPage() {
  const { data: settings } = useIrcSettings();
  const { data: status } = useIrcStatus(true);
  const { data: searchJobs } = useIrcSearchJobs();
  const { data: downloadJobs } = useIrcDownloadJobs();
  const updateSettings = useUpdateIrcSettings();
  const createSearchJob = useCreateIrcSearchJob();
  const connectIrc = useConnectIrc();
  const disconnectIrc = useDisconnectIrc();

  const [enabled, setEnabled] = useState(false);
  const [server, setServer] = useState("");
  const [port, setPort] = useState("6697");
  const [useTls, setUseTls] = useState(true);
  const [nickname, setNickname] = useState("");
  const [username, setUsername] = useState("");
  const [realName, setRealName] = useState("");
  const [channel, setChannel] = useState("");
  const [channelPassword, setChannelPassword] = useState("");
  const [autoMove, setAutoMove] = useState(true);
  const [testQuery, setTestQuery] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!settings) return;
    setEnabled(settings.enabled);
    setServer(settings.server);
    setPort(String(settings.port));
    setUseTls(settings.use_tls);
    setNickname(settings.nickname);
    setUsername(settings.username);
    setRealName(settings.real_name);
    setChannel(settings.channel);
    setChannelPassword("");
    setAutoMove(settings.auto_move_to_library);
  }, [settings]);

  const handleSave = async () => {
    await updateSettings.mutateAsync({
      enabled,
      server: server.trim(),
      port: Number(port) || 6697,
      use_tls: useTls,
      nickname: nickname.trim(),
      username: username.trim(),
      real_name: realName.trim(),
      channel: channel.trim(),
      channel_password: channelPassword,
      auto_move_to_library: autoMove,
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const statusTone =
    status?.state === "connected"
      ? "text-emerald-400"
      : status?.state === "connect_failed" || status?.state === "error" || status?.state === "invalid_config"
        ? "text-red-400"
        : "text-amber-400";

  return (
    <div className="max-w-4xl">
      <h2 className="text-2xl font-bold mb-1">Settings</h2>
      <div className="mb-6">
        <h3 className="text-lg font-semibold">IRC</h3>
        <p className="text-sm text-slate-400">
          Configure the single IRC connection used for search and DCC download jobs.
        </p>
      </div>

      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-6">
        <div className="flex items-start justify-between gap-6">
          <div>
            <h3 className="text-lg font-semibold mb-2">Connection</h3>
            <p className="text-sm text-slate-400">
              The worker logs every connection state change and queued job count to keep troubleshooting readable.
            </p>
          </div>
          <div className="text-right">
            <div className={`text-sm font-medium ${statusTone}`}>{status?.state ?? "loading"}</div>
            <div className="text-xs text-slate-500 mt-1">{status?.last_message ?? "No status yet"}</div>
            {status?.last_error && <div className="text-xs text-red-400 mt-1">{status.last_error}</div>}
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2 mt-6">
          <label className="flex items-center gap-3 text-sm text-slate-200">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="h-4 w-4 rounded border-slate-500 bg-slate-700 text-emerald-500 focus:ring-emerald-500"
            />
            Enable IRC integration
          </label>
          <label className="flex items-center gap-3 text-sm text-slate-200">
            <input
              type="checkbox"
              checked={useTls}
              onChange={(e) => setUseTls(e.target.checked)}
              className="h-4 w-4 rounded border-slate-500 bg-slate-700 text-emerald-500 focus:ring-emerald-500"
            />
            Use TLS
          </label>
          <div>
            <div className="text-xs text-slate-400 mb-1">Server</div>
            <input value={server} onChange={(e) => setServer(e.target.value)} className="w-full rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-slate-200" />
          </div>
          <div>
            <div className="text-xs text-slate-400 mb-1">Port</div>
            <input value={port} onChange={(e) => setPort(e.target.value)} className="w-full rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-slate-200" />
          </div>
          <div>
            <div className="text-xs text-slate-400 mb-1">Nickname</div>
            <input value={nickname} onChange={(e) => setNickname(e.target.value)} className="w-full rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-slate-200" />
          </div>
          <div>
            <div className="text-xs text-slate-400 mb-1">Username</div>
            <input value={username} onChange={(e) => setUsername(e.target.value)} className="w-full rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-slate-200" />
          </div>
          <div>
            <div className="text-xs text-slate-400 mb-1">Real Name</div>
            <input value={realName} onChange={(e) => setRealName(e.target.value)} className="w-full rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-slate-200" />
          </div>
          <div>
            <div className="text-xs text-slate-400 mb-1">Channel</div>
            <input value={channel} onChange={(e) => setChannel(e.target.value)} className="w-full rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-slate-200" placeholder="#books" />
          </div>
          <div className="md:col-span-2">
            <div className="text-xs text-slate-400 mb-1">Channel Password</div>
            <input value={channelPassword} onChange={(e) => setChannelPassword(e.target.value)} className="w-full rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-slate-200" placeholder={settings?.channel_password_set ? "Saved password present; enter to replace" : "Optional"} />
          </div>
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button
            onClick={handleSave}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500"
          >
            Save
          </button>
          <button
            onClick={() => connectIrc.mutate()}
            disabled={connectIrc.isPending}
            className="rounded-lg bg-slate-700 px-4 py-2 text-sm font-medium text-slate-200 transition-colors hover:bg-slate-600 disabled:opacity-50"
          >
            Connect
          </button>
          <button
            onClick={() => disconnectIrc.mutate()}
            disabled={disconnectIrc.isPending}
            className="rounded-lg bg-slate-700 px-4 py-2 text-sm font-medium text-slate-200 transition-colors hover:bg-slate-600 disabled:opacity-50"
          >
            Disconnect
          </button>
          {saved && <span className="text-sm text-emerald-400">IRC settings saved.</span>}
        </div>
      </div>

      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-6">
        <h3 className="text-lg font-semibold mb-4">Downloads</h3>
        <div className="flex items-center gap-3 mb-4 text-sm text-slate-200">
          <input
            type="checkbox"
            checked={autoMove}
            onChange={(e) => setAutoMove(e.target.checked)}
            className="h-4 w-4 rounded border-slate-500 bg-slate-700 text-emerald-500 focus:ring-emerald-500"
          />
          Automatically move completed IRC downloads into the library
        </div>
        <div className="text-sm text-slate-400">
          Downloads directory: <code className="text-slate-300">{settings?.downloads_dir ?? "/downloads"}</code>
        </div>
      </div>

      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-6">
        <h3 className="text-lg font-semibold mb-4">Test Search</h3>
        <p className="mb-4 text-sm text-slate-400">
          Queue a manual IRC search and watch the worker logs and job table update. This is useful while the DCC receive path is still being wired in.
        </p>
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <input
            value={testQuery}
            onChange={(e) => setTestQuery(e.target.value)}
            className="w-full rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm text-slate-100"
            placeholder="John Grisham The Activist"
          />
          <button
            type="button"
            onClick={() => createSearchJob.mutate({ query_text: testQuery })}
            disabled={createSearchJob.isPending || !testQuery.trim()}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {createSearchJob.isPending ? "Queueing..." : "Queue Search"}
          </button>
        </div>
        {createSearchJob.isError && (
          <div className="mt-3 text-sm text-rose-300">Failed to queue the test IRC search.</div>
        )}
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <div className="bg-slate-800 rounded-lg border border-slate-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold">Recent Search Jobs</h3>
            <span className="text-xs text-slate-500">{status?.queued_search_jobs ?? 0} queued</span>
          </div>
          <div className="space-y-3">
            {(searchJobs ?? []).length === 0 ? (
              <div className="text-sm text-slate-500">No IRC search jobs yet.</div>
            ) : (
              searchJobs?.map((job) => (
                <div key={job.id} className="rounded-lg border border-slate-700 bg-slate-900/30 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-medium text-slate-200">{job.query_text}</div>
                    <div className="text-xs text-slate-400">{job.status}</div>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    {job.expected_result_filename || "No expected result filename yet"}
                  </div>
                  {job.error_message && <div className="mt-1 text-xs text-red-400">{job.error_message}</div>}
                </div>
              ))
            )}
          </div>
        </div>

        <div className="bg-slate-800 rounded-lg border border-slate-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold">Recent Download Jobs</h3>
            <span className="text-xs text-slate-500">{status?.queued_download_jobs ?? 0} queued</span>
          </div>
          <div className="space-y-3">
            {(downloadJobs ?? []).length === 0 ? (
              <div className="text-sm text-slate-500">No IRC download jobs yet.</div>
            ) : (
              downloadJobs?.map((job) => (
                <div key={job.id} className="rounded-lg border border-slate-700 bg-slate-900/30 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-medium text-slate-200">{job.dcc_filename || "Pending filename"}</div>
                    <div className="text-xs text-slate-400">{job.status}</div>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    {job.moved_to_library_path || job.saved_path || "No file path yet"}
                  </div>
                  {job.error_message && <div className="mt-1 text-xs text-red-400">{job.error_message}</div>}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
