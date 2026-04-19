import { Navigate, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import AuthorsPage from "./pages/AuthorsPage";
import AuthorDetailPage from "./pages/AuthorDetailPage";
import BooksPage from "./pages/BooksPage";
import SettingsPage from "./pages/SettingsPage";
import LogsPage from "./pages/LogsPage";
import HiddenBooksPage from "./pages/HiddenBooksPage";
import UnmatchedFilesPage from "./pages/UnmatchedFilesPage";
import IrcSettingsPage from "./pages/IrcSettingsPage";
import IrcDownloadsPage from "./pages/IrcDownloadsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<AuthorsPage />} />
        <Route path="/authors/:id" element={<AuthorDetailPage />} />
        <Route path="/books" element={<BooksPage />} />
        <Route path="/books/hidden" element={<HiddenBooksPage />} />
        <Route path="/irc-downloads" element={<IrcDownloadsPage />} />
        <Route path="/settings" element={<Navigate to="/settings/api-keys" replace />} />
        <Route path="/settings/api-keys" element={<SettingsPage section="api-keys" />} />
        <Route path="/settings/profiles" element={<SettingsPage section="profiles" />} />
        <Route path="/settings/metadata-refreshes" element={<SettingsPage section="metadata-refreshes" />} />
        <Route path="/settings/unmatched-files" element={<UnmatchedFilesPage />} />
        <Route path="/settings/irc" element={<IrcSettingsPage />} />
        <Route path="/settings/logs" element={<LogsPage />} />
        <Route path="/logs" element={<Navigate to="/settings/logs" replace />} />
      </Route>
    </Routes>
  );
}
