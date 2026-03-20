import { Link } from "react-router-dom";
import type { Author } from "../types";
import { getImageUrl } from "../types";

export default function AuthorCard({ author }: { author: Author }) {
  const imgUrl = getImageUrl(author.image_cached_path, author.image_url);

  return (
    <Link
      to={`/authors/${author.id}`}
      className="group bg-slate-800 rounded-lg border border-slate-700 overflow-hidden hover:border-emerald-500/50 transition-all hover:shadow-lg hover:shadow-emerald-500/10"
    >
      <div className="aspect-[3/4] bg-slate-700 overflow-hidden">
        {imgUrl ? (
          <img
            src={imgUrl}
            alt={author.name}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-4xl font-bold text-slate-500">
            {author.name.charAt(0)}
          </div>
        )}
      </div>
      <div className="p-3">
        <h3 className="font-semibold text-slate-100 truncate group-hover:text-emerald-400 transition-colors">
          {author.name}
        </h3>
        <p className="text-sm text-slate-400 mt-1">
          <span className="text-emerald-400 font-medium">{author.book_count_local}</span>
          <span className="text-slate-500"> / {author.book_count_total} books</span>
        </p>
      </div>
    </Link>
  );
}
