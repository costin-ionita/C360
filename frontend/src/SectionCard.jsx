import { useEffect, useRef } from 'react'

/** Renders one report section's server-rendered HTML fragment (from
 * dashboard/render.py) inside a uniform card shell. The title/border/spacing
 * are owned here, not by the backend -- see the note in dashboard/render.py's
 * module docstring on why fragments carry no chrome of their own. */
export default function SectionCard({ section }) {
  const contentRef = useRef(null)

  useEffect(() => {
    const container = contentRef.current
    if (!container) return
    // dangerouslySetInnerHTML does not execute <script> tags (a DOM security
    // quirk) -- re-create them so the price chart's hover/tooltip JS actually runs.
    container.querySelectorAll('script').forEach((oldScript) => {
      const newScript = document.createElement('script')
      Array.from(oldScript.attributes).forEach((attr) => newScript.setAttribute(attr.name, attr.value))
      newScript.textContent = oldScript.textContent
      oldScript.replaceWith(newScript)
    })
  }, [section.html])

  return (
    <section
      className="rounded-lg p-5"
      style={{ background: 'var(--surface-1)', border: '1px solid var(--border)' }}
    >
      {section.title && (
        <h2 className="text-sm font-semibold mb-3" style={{ color: 'var(--text-secondary)' }}>
          {section.title}
        </h2>
      )}
      <div ref={contentRef} dangerouslySetInnerHTML={{ __html: section.html }} />
    </section>
  )
}
