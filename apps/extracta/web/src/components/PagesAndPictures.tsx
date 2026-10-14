import type { OutputItem, PageLink, PictureSummary } from "../types";

export function PagesSection({ pages, outputs }: { pages: PageLink[]; outputs: OutputItem[] }) {
  const index = outputs.find((output) => output.format === "pages_html");
  return (
    <section className="tables">
      <div className="tables-head">
        <h3>
          Pages <span className="muted">({pages.length} HTML files)</span>
        </h3>
        {index && (
          <a className="btn" href={index.url} target="_blank" rel="noreferrer">
            Open page index
          </a>
        )}
      </div>
      <div className="page-links">
        {pages.map((page) => (
          <a key={page.page} className="page-link" href={page.url} target="_blank" rel="noreferrer" title={page.heading ?? ""}>
            <strong>{page.page}</strong>
            {page.heading && <span className="muted small">{page.heading}</span>}
          </a>
        ))}
      </div>
    </section>
  );
}

export function PicturesSection({ pictures, outputs }: { pictures: PictureSummary[]; outputs: OutputItem[] }) {
  const manifest = outputs.find((output) => output.format === "pictures_json");
  return (
    <section className="tables">
      <div className="tables-head">
        <h3>
          Images <span className="muted">({pictures.length})</span>
        </h3>
        {manifest && (
          <a className="btn ghost" href={manifest.url} download={manifest.filename}>
            Metadata (JSON)
          </a>
        )}
      </div>
      <div className="picture-grid">
        {pictures.map((picture) => (
          <figure key={picture.picture_id} className="picture-card">
            <a href={picture.files.image} target="_blank" rel="noreferrer">
              <img src={picture.files.image} alt={picture.caption ?? `Image ${picture.index}`} loading="lazy" />
            </a>
            <figcaption>
              <span className="small">
                {picture.page !== null ? `Page ${picture.page}` : `Image ${picture.index}`} · {picture.width_px}×
                {picture.height_px}
              </span>
              {picture.caption && <span className="muted small picture-caption">{picture.caption}</span>}
              <a className="small" href={picture.files.image} download>
                Download
              </a>
            </figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}
