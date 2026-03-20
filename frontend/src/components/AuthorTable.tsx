import { Link } from "react-router-dom";
import type { Author } from "../types";
import { getImageUrl } from "../types";

export default function AuthorTable({ authors }: { authors: Author[] }) {
  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
      <table className="w-full text-sm text-left">
        <thead className="text-xs uppercase text-slate-400 bg-slate-800/80 border-b border-slate-700">
          <tr>
            <th className="px-4 py-3 w-12"></th>
            <th className="px-4 py-3">Author</th>
            <th className="px-4 py-3 text-right">Owned</th>
            <th className="px-4 py-3 text-right">Total</th>
            <th className="px-4 py-3 text-right">Completion</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700">
          {authors.map((author) => {
            const imgUrl = getImageUrl(author.image_cached_path, author.image_url);
            const pct = author.book_count_total > 0
              ? Math.round((author.book_count_local / author.book_count_total) * 100)
              : 0;
            return (
              <tr key={author.id} className="hover:bg-slate-700/50 transition-colors">
                <td className="px-4 py-2">
                  <div className="w-8 h-8 rounded-full overflow-hidden bg-slate-700 flex-shrink-0">
                    {imgUrl ? (
                      <img src={imgUrl} alt="" className="w-full h-full object-cover" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-xs font-bold text-slate-500">
                        {author.name.charAt(0)}
                      </div>
                    )}
                  </div>
                </td>
                <td className="px-4 py-2">
                  <Link
                    to={`/authors/${author.id}`}
                    className="font-medium text-slate-200 hover:text-emerald-400 transition-colors"
                  >
                    {author.name}
                  </Link>
                </td>
                <td className="px-4 py-2 text-right text-emerald-400 font-medium">
                  {author.book_count_local}
                </td>
                <td className="px-4 py-2 text-right text-slate-300">
                  {author.book_count_total}
                </td>
                <td className="px-4 py-2 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <div className="w-20 bg-slate-700 rounded-full h-1.5">
                      <div
                        className="bg-emerald-500 h-1.5 rounded-full"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-slate-400 text-xs w-8 text-right">{pct}%</span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
