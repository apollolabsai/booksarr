import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import AuthorsPage from "./pages/AuthorsPage";
import AuthorDetailPage from "./pages/AuthorDetailPage";
import BooksPage from "./pages/BooksPage";
import SettingsPage from "./pages/SettingsPage";
import LogsPage from "./pages/LogsPage";
import HiddenBooksPage from "./pages/HiddenBooksPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<AuthorsPage />} />
        <Route path="/authors/:id" element={<AuthorDetailPage />} />
        <Route path="/books" element={<BooksPage />} />
        <Route path="/books/hidden" element={<HiddenBooksPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/logs" element={<LogsPage />} />
      </Route>
    </Routes>
  );
}
